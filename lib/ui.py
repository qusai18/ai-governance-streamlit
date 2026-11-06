"""Streamlit glue: secrets, sign-in, the shared Lakebase store and cached reads."""
from __future__ import annotations

import getpass
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from lib.aicm_parse import parse_aicm, parse_caiq
from lib.connection import Settings, make_pool, running_as_databricks_app
from lib.store import Store

DATA = Path(__file__).resolve().parent.parent / "data"


# ------------------------------------------------------------------ secrets
def secret_section(name: str) -> dict:
    """Return a [section] of .streamlit/secrets.toml, or {} when there is none."""
    try:
        if name in st.secrets:
            return dict(st.secrets[name])
    except Exception:  # no secrets.toml at all (e.g. on Databricks Apps)
        pass
    return {}


# ------------------------------------------------------------------ identity
def _allowed(email: str, app_cfg: dict) -> bool:
    emails = [e.lower() for e in app_cfg.get("allowed_emails", [])]
    domains = [d.lower().lstrip("@") for d in app_cfg.get("allowed_domains", [])]
    if not emails and not domains:
        return True
    email = email.lower()
    return email in emails or email.split("@")[-1] in domains


def require_user() -> tuple[str, str]:
    """Return (actor, auth_source) for the person using the app, or stop the page.

    * Databricks App: the platform signs users in with workspace SSO and passes their email.
    * Elsewhere: Streamlit's OIDC login (st.login) when an [auth] section is configured,
      optionally limited by [app] allowed_emails / allowed_domains.
    * Local development only: [app] allow_unauthenticated = true.
    """
    if "identity" in st.session_state:
        return st.session_state["identity"]

    if running_as_databricks_app():
        h = st.context.headers
        email = h.get("X-Forwarded-Email") or h.get("X-Forwarded-Preferred-Username") or h.get("X-Forwarded-User")
        ident = (email or "unknown-databricks-user", "databricks-sso")
    else:
        app_cfg = secret_section("app")
        if secret_section("auth"):
            if not st.user.is_logged_in:
                st.title("AI Governance Platform")
                st.write("Sign in to continue.")
                st.button("Sign in", type="primary", on_click=st.login)
                st.stop()
            email = st.user.get("email") or st.user.get("preferred_username") or "unknown"
            if not _allowed(email, app_cfg):
                st.error(f"{email} is not allowed to use this app.")
                st.button("Sign out", on_click=st.logout)
                st.stop()
            ident = (email, "oidc")
        elif app_cfg.get("allow_unauthenticated"):
            ident = (f"local:{getpass.getuser()}", "unauthenticated-local")
        else:
            st.error(
                "Sign-in is not configured. Add an [auth] section to .streamlit/secrets.toml "
                "(see secrets.toml.example), or for local development only set "
                "[app] allow_unauthenticated = true."
            )
            st.stop()

    st.session_state["identity"] = ident
    try:
        store().audit(ident[0], ident[1], "session.start", "app", None, None)
    except Exception:
        pass  # never block sign-in on the audit write; errors surface on the next real write
    return ident


def actor() -> str:
    return st.session_state["identity"][0]


def audit(action: str, entity: str, entity_id: str | None = None, detail: str | None = None) -> None:
    ident = st.session_state["identity"]
    store().audit(ident[0], ident[1], action, entity, entity_id, detail)


# ------------------------------------------------------------------ store
@st.cache_resource(show_spinner="Connecting to Lakebase ...")
def store() -> Store:
    settings = Settings.load(secret_section("databricks"), secret_section("lakebase"))
    s = Store(make_pool(settings), settings.schema)
    _bootstrap(s)
    return s


def _bootstrap(s: Store) -> None:
    """Create tables on first start and seed the AICM / AI-CAIQ reference data if empty."""
    has_tables = s.query("SELECT to_regclass(%(t)s) AS t", {"t": f"{s.schema}.audit_log"}).t[0]
    if not has_tables:
        s.ensure_schema()
    # Extra Postgres roles (e.g. the service principal a Streamlit Cloud copy uses) that should get
    # read/write access. Only the schema owner can grant, so this is set on the Databricks App.
    for role in filter(None, (r.strip() for r in os.environ.get("AIGOV_GRANT_ROLES", "").split(","))):
        s.grant_access(role)
    controls, questions = s.reference_counts()
    if controls == 0 or questions == 0:
        c = parse_aicm(str(DATA / "AICMv1.1.1.xlsx"))
        q = parse_caiq(str(DATA / "AI-CAIQv1.1.0_template.xlsx"))
        s.load_reference_data(c, q)
        s.audit("system:bootstrap", "app", "reference.load", "aicm_controls", None,
                f"{len(c)} controls (AICM {c[0]['aicm_version']}), {len(q)} questions")


# ------------------------------------------------------------------ cached reads
@st.cache_data(ttl=3600, show_spinner=False)
def controls() -> pd.DataFrame:
    return store().controls()


@st.cache_data(ttl=3600, show_spinner=False)
def questions() -> pd.DataFrame:
    return store().questions()


@st.cache_data(ttl=60, show_spinner=False)
def systems() -> pd.DataFrame:
    return store().systems()


@st.cache_data(ttl=60, show_spinner=False)
def findings(system_id: str | None = None) -> pd.DataFrame:
    return store().findings(system_id)


@st.cache_data(ttl=60, show_spinner=False)
def answers(system_id: str | None = None) -> pd.DataFrame:
    return store().answers(system_id)


def refresh() -> None:
    """Drop cached inventory, findings and answers after a write."""
    systems.clear()
    findings.clear()
    answers.clear()


def system_picker(label: str = "AI system", key: str = "system") -> pd.Series | None:
    df = systems()
    if df.empty:
        st.info("No AI systems yet. Add one or import a workspace export on the **AI systems** page.")
        return None
    ids = df.system_id.tolist()
    names = dict(zip(df.system_id, df.name))
    default = st.session_state.get("current_system")
    idx = ids.index(default) if default in ids else 0
    sid = st.selectbox(label, ids, index=idx, format_func=lambda i: f"{names[i]} ({i})", key=key)
    st.session_state["current_system"] = sid
    return df[df.system_id == sid].iloc[0]


def assessment_frame(system_id: str) -> pd.DataFrame:
    """One row per AI-CAIQ question, joined to its control and this system's answer."""
    q = questions()
    c = controls()[["control_id", "domain", "domain_code", "title", "control_type"]]
    a = answers(system_id)
    df = q.merge(c, on="control_id", how="left")
    cols = ["question_id", "answer", "ssrm_owner", "implementation", "customer_responsibility",
            "updated_at", "updated_by"]
    if a.empty:
        a = pd.DataFrame(columns=cols)
    df = df.merge(a[cols], on="question_id", how="left")
    for col in ("answer", "ssrm_owner", "implementation", "customer_responsibility"):
        df[col] = df[col].astype("object").where(df[col].notna(), None)
    return df.sort_values("seq").reset_index(drop=True)
