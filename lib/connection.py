"""Lakebase (Postgres) connection settings shared by the Streamlit app and the setup script.

The same code runs in two places:

* As a Databricks App: the `postgres` resource in app.yaml makes the platform inject PGHOST,
  PGDATABASE, PGUSER (the app's service principal), PGPORT, PGSSLMODE and LAKEBASE_ENDPOINT,
  plus DATABRICKS_HOST / DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET for that principal.
* Anywhere else (your laptop, Streamlit Community Cloud): values come from
  `.streamlit/secrets.toml` ([databricks] and [lakebase] sections) or environment variables.

Lakebase accepts a short-lived Databricks OAuth token as the Postgres password; a fresh one is
generated for every new connection, so nothing long-lived is ever stored.
No Streamlit import here, so scripts can use it too.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from psycopg_pool import ConnectionPool

TOKEN_REFRESH_SECONDS = 30 * 60  # tokens live 1 hour; refresh well before that
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def running_as_databricks_app() -> bool:
    return bool(os.environ.get("DATABRICKS_APP_NAME"))


@dataclass
class Settings:
    endpoint: str                       # projects/<p>/branches/<b>/endpoints/<e>
    pg_host: str
    pg_user: str | None = None          # defaults to the authenticated Databricks identity
    pg_database: str = "databricks_postgres"
    pg_port: int = 5432
    schema: str = "aigov"
    # Databricks identity used to mint Lakebase tokens, first match wins:
    host: str | None = None
    client_id: str | None = None        # service principal (OAuth M2M), preferred outside Databricks
    client_secret: str | None = None
    profile: str | None = None          # ~/.databrickscfg profile, for local development

    @classmethod
    def load(cls, databricks: dict | None = None, lakebase: dict | None = None) -> "Settings":
        """Build settings from secrets sections with environment-variable fallbacks."""
        d = {k: v for k, v in (databricks or {}).items() if v not in (None, "")}
        lb = {k: v for k, v in (lakebase or {}).items() if v not in (None, "")}
        endpoint = lb.get("endpoint") or os.environ.get("LAKEBASE_ENDPOINT")
        pg_host = lb.get("host") or os.environ.get("PGHOST")
        if not endpoint or not pg_host:
            raise RuntimeError(
                "Lakebase is not configured. On Databricks Apps add the `postgres` resource; elsewhere set "
                "[lakebase] endpoint and host in .streamlit/secrets.toml (see secrets.toml.example)."
            )
        schema = lb.get("schema") or os.environ.get("AIGOV_SCHEMA", "aigov")
        if not _IDENT.match(schema):
            raise ValueError("schema may only contain lowercase letters, digits and underscores")
        return cls(
            endpoint=endpoint,
            pg_host=pg_host,
            pg_user=lb.get("user") or os.environ.get("PGUSER"),
            pg_database=lb.get("database") or os.environ.get("PGDATABASE", "databricks_postgres"),
            pg_port=int(lb.get("port") or os.environ.get("PGPORT", 5432)),
            schema=schema,
            host=d.get("host"),
            client_id=d.get("client_id"),
            client_secret=d.get("client_secret"),
            profile=d.get("profile"),
        )

    def workspace_client(self) -> WorkspaceClient:
        if self.client_id and self.client_secret:
            cfg = Config(host=self.host, client_id=self.client_id, client_secret=self.client_secret)
        elif self.profile:
            cfg = Config(profile=self.profile)
        else:
            cfg = Config()  # Databricks App service principal, or DATABRICKS_* env vars
        return WorkspaceClient(config=cfg)


class TokenSource:
    """Caches a Lakebase OAuth token and refreshes it every 30 minutes."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = settings.workspace_client()
        self._lock = threading.Lock()
        self._token: str | None = None
        self._minted = 0.0
        self.user = settings.pg_user or self._identity()

    def _identity(self) -> str:
        # Service principals log in to Postgres with their application (client) ID.
        client_id = self.settings.client_id or self.client.config.client_id
        if client_id:
            return client_id
        # For a user this is their email; for a service principal SCIM returns the application ID.
        return self.client.current_user.me().user_name

    def token(self) -> str:
        with self._lock:
            if not self._token or time.time() - self._minted > TOKEN_REFRESH_SECONDS:
                cred = self.client.postgres.generate_database_credential(endpoint=self.settings.endpoint)
                self._token, self._minted = cred.token, time.time()
            return self._token


def make_pool(settings: Settings, min_size: int = 1, max_size: int = 5) -> ConnectionPool:
    tokens = TokenSource(settings)

    class LakebaseConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):
            kwargs["password"] = tokens.token()
            return super().connect(conninfo, **kwargs)

    pool = ConnectionPool(
        conninfo="",
        connection_class=LakebaseConnection,
        kwargs={
            "host": settings.pg_host,
            "port": settings.pg_port,
            "dbname": settings.pg_database,
            "user": tokens.user,
            "sslmode": "require",
            "application_name": "ai-governance-streamlit",
            "autocommit": True,
        },
        min_size=min_size,
        max_size=max_size,
        max_lifetime=45 * 60,     # recycle before the token used at login would expire
        max_idle=10 * 60,
        check=ConnectionPool.check_connection,  # detects connections dropped by scale-to-zero
        open=True,
        timeout=60,
    )
    pool.pg_user = tokens.user  # type: ignore[attr-defined]
    return pool
