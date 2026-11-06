"""Data access for the AI governance platform on Lakebase Postgres.

All SQL uses bound parameters (%(name)s); values are never formatted into SQL text.
The schema name is validated in Settings and quoted here.
"""
from __future__ import annotations

import uuid
from typing import Sequence

import pandas as pd
from psycopg.rows import dict_row

CAIQ_ANSWERS = ["Yes", "No", "NA"]
SSRM_OWNERS = [
    "Owned by CSP",
    "Owned by MP",
    "Owned by OSP",
    "Owned by AP",
    "Owned by AIC",
    "Shared across the supply chain",
    "Shared CSP-MP",
    "Shared MP-OSP",
    "Shared OSP-AP",
    "Shared AP-AIC",
    "Not Determined",
]
ROLES = {
    "CSP": "Cloud Service Provider",
    "MP": "Model Provider",
    "OSP": "Orchestrated Service Provider",
    "AP": "Application Provider",
    "AIC": "AI Customer",
}
FINDING_STATUSES = ["Open", "In remediation", "Accepted risk", "Resolved", "Not applicable"]
COMPONENT_TYPES = ["service", "model", "agent", "data", "infra", "other"]

CONTROL_COLUMNS = [
    "control_id", "domain", "domain_code", "title", "specification", "control_type",
    "owner_csp", "owner_mp", "owner_osp", "owner_ap",
    "arch_phys", "arch_network", "arch_compute", "arch_storage", "arch_app", "arch_data",
    "lc_preparation", "lc_development", "lc_evaluation", "lc_deployment", "lc_delivery", "lc_retirement",
    "threat_model_manipulation", "threat_data_poisoning", "threat_sensitive_data_disclosure",
    "threat_model_theft", "threat_service_failure", "threat_supply_chain", "threat_insecure_plugins",
    "threat_dos", "threat_governance",
    "impl_shared", "impl_mp", "impl_osp", "impl_ap", "impl_aic", "impl_csp",
    "audit_ap", "audit_osp", "audit_mp", "audit_aic", "audit_csp",
    "map_aiuc1", "gap_aiuc1", "add_aiuc1", "map_bsi_c4", "gap_bsi_c4", "add_bsi_c4",
    "map_eu_ai_act", "gap_eu_ai_act", "add_eu_ai_act", "map_iso42001", "gap_iso42001", "add_iso42001",
    "map_nist_ai_rmf", "gap_nist_ai_rmf", "add_nist_ai_rmf",
    "aicm_version",
]
BOOL_CONTROL_COLUMNS = {c for c in CONTROL_COLUMNS if c.startswith(("arch_", "threat_"))}
QUESTION_COLUMNS = ["question_id", "control_id", "question", "seq", "caiq_version"]
SYSTEM_COLUMNS = [
    "system_id", "name", "component_type", "role", "vendor", "layers", "phases",
    "flag_internet", "flag_sensitive", "flag_untrusted", "flag_third_party", "notes", "source",
]
FINDING_COLUMNS = ["finding_id", "system_id", "control_id", "note", "evidence", "observed_at", "source", "status"]
ANSWER_COLUMNS = ["question_id", "answer", "ssrm_owner", "implementation", "customer_responsibility"]


def _list(values: Sequence[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def schema_ddl(s: str) -> list[str]:
    q = f'"{s}"'
    ctrl_cols = ",\n  ".join(
        f"{c} {'BOOLEAN' if c in BOOL_CONTROL_COLUMNS else 'TEXT'}" for c in CONTROL_COLUMNS[1:]
    )
    stamps = ("created_at TIMESTAMPTZ NOT NULL DEFAULT now(), created_by TEXT, "
              "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_by TEXT")
    return [
        f"CREATE SCHEMA IF NOT EXISTS {q}",
        f"""CREATE TABLE IF NOT EXISTS {q}.aicm_controls (
  control_id TEXT PRIMARY KEY,
  {ctrl_cols}
)""",
        f"""CREATE TABLE IF NOT EXISTS {q}.caiq_questions (
  question_id TEXT PRIMARY KEY,
  control_id TEXT NOT NULL REFERENCES {q}.aicm_controls(control_id),
  question TEXT NOT NULL,
  seq INTEGER NOT NULL,
  caiq_version TEXT
)""",
        f"""CREATE TABLE IF NOT EXISTS {q}.ai_systems (
  system_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  component_type TEXT,
  role TEXT CHECK (role IS NULL OR role IN ({_list(list(ROLES))})),
  vendor TEXT, layers TEXT, phases TEXT,
  flag_internet BOOLEAN NOT NULL DEFAULT false, flag_sensitive BOOLEAN NOT NULL DEFAULT false,
  flag_untrusted BOOLEAN NOT NULL DEFAULT false, flag_third_party BOOLEAN NOT NULL DEFAULT false,
  notes TEXT, source TEXT,
  {stamps}
)""",
        f"""CREATE TABLE IF NOT EXISTS {q}.findings (
  finding_id TEXT PRIMARY KEY,
  system_id TEXT NOT NULL REFERENCES {q}.ai_systems(system_id) ON DELETE CASCADE,
  control_id TEXT NOT NULL,
  note TEXT NOT NULL, evidence TEXT, observed_at TIMESTAMPTZ, source TEXT,
  status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ({_list(FINDING_STATUSES)})),
  {stamps}
)""",
        f"""CREATE TABLE IF NOT EXISTS {q}.caiq_answers (
  system_id TEXT NOT NULL REFERENCES {q}.ai_systems(system_id) ON DELETE CASCADE,
  question_id TEXT NOT NULL REFERENCES {q}.caiq_questions(question_id),
  answer TEXT CHECK (answer IS NULL OR answer IN ({_list(CAIQ_ANSWERS)})),
  ssrm_owner TEXT CHECK (ssrm_owner IS NULL OR ssrm_owner IN ({_list(SSRM_OWNERS)})),
  implementation TEXT, customer_responsibility TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_by TEXT,
  PRIMARY KEY (system_id, question_id)
)""",
        f"""CREATE TABLE IF NOT EXISTS {q}.audit_log (
  id BIGSERIAL PRIMARY KEY,
  event_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor TEXT NOT NULL, auth_source TEXT, action TEXT NOT NULL,
  entity TEXT, entity_id TEXT, detail TEXT
)""",
        # Append-only audit trail. Deliberately not wrapped in error handling: if this
        # fails, startup fails, rather than leaving a silently mutable log.
        f"""CREATE OR REPLACE FUNCTION {q}.audit_log_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP;
END $$""",
        f"DROP TRIGGER IF EXISTS audit_log_no_change ON {q}.audit_log",
        f"""CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON {q}.audit_log
FOR EACH ROW EXECUTE FUNCTION {q}.audit_log_immutable()""",
        f"DROP TRIGGER IF EXISTS audit_log_no_truncate ON {q}.audit_log",
        f"""CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON {q}.audit_log
FOR EACH STATEMENT EXECUTE FUNCTION {q}.audit_log_immutable()""",
        f"CREATE INDEX IF NOT EXISTS findings_system_idx ON {q}.findings(system_id)",
        f"CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON {q}.audit_log(event_ts DESC)",
    ]


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if v is pd.NaT:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy scalars
        try:
            return v.item()
        except Exception:
            return v
    return v


class Store:
    def __init__(self, pool, schema: str):
        self.pool = pool
        self.s = f'"{schema}"'
        self.schema = schema

    # ------------------------------------------------------------ low level
    def execute(self, sql: str, params: dict | None = None) -> None:
        with self.pool.connection() as conn:
            conn.execute(sql, params or {})

    def executemany(self, sql: str, rows: list[dict]) -> None:
        if not rows:
            return
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(sql, [{k: _clean(v) for k, v in r.items()} for r in rows])

    def query(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params or {})
                rows = cur.fetchall()
                cols = [c.name for c in cur.description] if cur.description else []
        return pd.DataFrame(rows, columns=cols)

    def _upsert_sql(self, table: str, cols: list[str], key: list[str], stamp: bool = True) -> str:
        names = ", ".join(cols)
        values = ", ".join(f"%({c})s" for c in cols)
        updates = [f"{c} = EXCLUDED.{c}" for c in cols if c not in key]
        extra_cols = extra_vals = ""
        if stamp:
            extra_cols = ", created_by, updated_by"
            extra_vals = ", %(_actor)s, %(_actor)s"
            updates += ["updated_at = now()", "updated_by = EXCLUDED.updated_by"]
        return (f"INSERT INTO {self.s}.{table} ({names}{extra_cols}) VALUES ({values}{extra_vals}) "
                f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {', '.join(updates)}")

    # ------------------------------------------------------------ setup
    def ensure_schema(self) -> None:
        with self.pool.connection() as conn:
            with conn.transaction():
                for stmt in schema_ddl(self.schema):
                    conn.execute(stmt)

    def grant_access(self, role: str) -> None:
        """Give another Postgres role (e.g. a Streamlit Cloud service principal) read/write use of
        this schema. Must run as the schema owner, i.e. inside the deployed Databricks App."""
        from psycopg import sql

        r, sch = sql.Identifier(role), sql.Identifier(self.schema)
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sch, r))
                conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(sch, r))
                conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(sch, r))
                conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(sch, r))

    def reference_counts(self) -> tuple[int, int]:
        df = self.query(f"SELECT (SELECT count(*) FROM {self.s}.aicm_controls) AS c, "
                        f"(SELECT count(*) FROM {self.s}.caiq_questions) AS q")
        return int(df.c[0]), int(df.q[0])

    def load_reference_data(self, controls: list[dict], questions: list[dict]) -> None:
        self.executemany(self._upsert_sql("aicm_controls", CONTROL_COLUMNS, ["control_id"], stamp=False),
                         [{c: r.get(c) for c in CONTROL_COLUMNS} for r in controls])
        self.executemany(self._upsert_sql("caiq_questions", QUESTION_COLUMNS, ["question_id"], stamp=False),
                         [{c: r.get(c) for c in QUESTION_COLUMNS} for r in questions])

    # ------------------------------------------------------------ reference data
    def controls(self) -> pd.DataFrame:
        return self.query(f"SELECT * FROM {self.s}.aicm_controls ORDER BY domain_code, control_id")

    def questions(self) -> pd.DataFrame:
        return self.query(f"SELECT * FROM {self.s}.caiq_questions ORDER BY seq")

    # ------------------------------------------------------------ audit
    def audit(self, actor: str, auth_source: str, action: str, entity: str,
              entity_id: str | None = None, detail: str | None = None) -> None:
        self.execute(
            f"INSERT INTO {self.s}.audit_log (actor, auth_source, action, entity, entity_id, detail) "
            "VALUES (%(actor)s, %(src)s, %(action)s, %(entity)s, %(eid)s, %(detail)s)",
            {"actor": actor, "src": auth_source, "action": action, "entity": entity,
             "eid": entity_id, "detail": (detail or "")[:4000]},
        )

    def audit_log(self, limit: int = 500) -> pd.DataFrame:
        return self.query(f"SELECT * FROM {self.s}.audit_log ORDER BY event_ts DESC LIMIT %(n)s",
                          {"n": int(limit)})

    # ------------------------------------------------------------ inventory
    def systems(self) -> pd.DataFrame:
        return self.query(f"SELECT * FROM {self.s}.ai_systems ORDER BY name")

    def upsert_systems(self, recs: list[dict], actor: str) -> None:
        self.executemany(self._upsert_sql("ai_systems", SYSTEM_COLUMNS, ["system_id"]),
                         [{**{c: r.get(c) for c in SYSTEM_COLUMNS}, "_actor": actor} for r in recs])

    def delete_system(self, system_id: str) -> None:
        # Findings and answers go with it (ON DELETE CASCADE).
        self.execute(f"DELETE FROM {self.s}.ai_systems WHERE system_id = %(sid)s", {"sid": system_id})

    # ------------------------------------------------------------ findings
    def findings(self, system_id: str | None = None) -> pd.DataFrame:
        where, params = "", {}
        if system_id:
            where, params = "WHERE system_id = %(sid)s", {"sid": system_id}
        return self.query(f"SELECT * FROM {self.s}.findings {where} ORDER BY control_id, created_at", params)

    def upsert_findings(self, recs: list[dict], actor: str) -> None:
        self.executemany(self._upsert_sql("findings", FINDING_COLUMNS, ["finding_id"]),
                         [{**{c: r.get(c) for c in FINDING_COLUMNS}, "_actor": actor} for r in recs])

    # ------------------------------------------------------------ CAIQ answers
    def answers(self, system_id: str | None = None) -> pd.DataFrame:
        where, params = "", {}
        if system_id:
            where, params = "WHERE system_id = %(sid)s", {"sid": system_id}
        return self.query(f"SELECT * FROM {self.s}.caiq_answers {where}", params)

    def save_answers(self, system_id: str, rows: list[dict], actor: str) -> None:
        cols = ["system_id"] + ANSWER_COLUMNS
        names = ", ".join(cols)
        values = ", ".join(f"%({c})s" for c in cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in ANSWER_COLUMNS[1:])
        sql = (f"INSERT INTO {self.s}.caiq_answers ({names}, updated_by) VALUES ({values}, %(_actor)s) "
               f"ON CONFLICT (system_id, question_id) DO UPDATE SET {updates}, "
               "updated_at = now(), updated_by = EXCLUDED.updated_by")
        self.executemany(sql, [{**{c: r.get(c) for c in ANSWER_COLUMNS}, "system_id": system_id,
                                "_actor": actor} for r in rows])


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"
