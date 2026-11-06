# AI Governance Platform (Streamlit + Databricks Lakebase)

A Streamlit app for governing AI systems against the **CSA AI Controls Matrix (AICM) v1.1.1**
and preparing a **STAR for AI Level 1** self-assessment (AI-CAIQ v1.1.0).

| Page | What it does |
|---|---|
| Dashboard | Portfolio progress, STAR blockers, completion and Yes/No/NA mix by domain, findings |
| AI systems | Inventory (role, layers, lifecycle phases, risk flags), findings with status, import of an `aicm-mapper` workspace JSON |
| AI-CAIQ assessment | Answer all 320 questions in a grid (answer, SSRM owner, implementation, customer duties), CSA decision-rule checks, fill blank owners from the AICM for your role, control guidance and open findings alongside |
| STAR export | Validation summary and download of the original CSA AI-CAIQ workbook with columns C–F filled, plus the submission checklist |
| AICM controls | All 247 controls with filters (domain, type, threat, layer, framework gap), implementation and auditing guidelines per role, EU AI Act / ISO 42001 / NIST AI RMF / AIUC-1 / BSI AI C4 mappings |
| Audit log | Append-only trail of sign-ins and every change (a trigger blocks UPDATE/DELETE/TRUNCATE) |

## Architecture

- **UI**: Streamlit (`app.py`, `app_pages/`).
- **Data**: Lakebase Postgres project `ai-governance`, branch `production`, database
  `databricks_postgres`, schema `aigov` (tables in `lib/store.py`). Unity Catalog managed tables were
  the first choice, but this workspace's metastore storage currently returns S3 403 on table creation.
- **Auth to the database**: short-lived Databricks OAuth tokens as the Postgres password, minted per
  connection (`lib/connection.py`); nothing long-lived is stored.
- **Reference data**: `data/AICMv1.1.1.xlsx` and `data/AI-CAIQv1.1.0_template.xlsx` are parsed
  (`lib/aicm_parse.py`) and seeded automatically on first start.

## Running it

### 1. As a Databricks App (deployed)

URL: https://ai-governance-8111738034870929.aws.databricksapps.com. Users sign in with workspace SSO;
anyone you give **CAN USE** on the app can use it. Redeploy after changes:

```bash
databricks apps deploy -t dev --profile DEFAULT
```

The app's service principal owns the `aigov` schema (it creates it on first start).

### 2. On your laptop

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # then edit
.venv\Scripts\python -m streamlit run app.py
```

Use `schema = "aigov_dev"` in `secrets.toml` for a private dev copy, or `"aigov"` to work on the
shared data (your user is the Lakebase project owner, so it has access).

### 3. On Streamlit Community Cloud (or any other host)

1. Create a Databricks **service principal** with an OAuth secret (Workspace settings → Identity and
   access → Service principals). Don't use a personal access token.
2. Add it as a Lakebase role: Lakebase → `ai-governance` → Branch `production` → Roles → Add role.
3. Let the app grant it access: set `AIGOV_GRANT_ROLES` to the service principal's application ID in
   `app.yaml` and `databricks.yml`, then redeploy (only the schema owner, the app, can grant).
4. In Streamlit Cloud → App settings → Secrets, paste `.streamlit/secrets.toml.example` with
   `client_id` / `client_secret` for that service principal and `schema = "aigov"`.
5. Configure sign-in in the `[auth]` section (Streamlit OIDC, e.g. Microsoft Entra ID) and restrict
   it with `[app] allowed_domains`. Never set `allow_unauthenticated` on a shared deployment.

## Maintenance

```bash
# Import or re-import an aicm-mapper export (updates in place)
.venv\Scripts\python scripts\setup_databricks.py --import-inventory data\<export>.json
# Reload the AICM / AI-CAIQ reference data after a new CSA release
.venv\Scripts\python scripts\setup_databricks.py --reload-reference
```

## How this addresses the repo-scan findings for the old Next.js app

| Finding | Here |
|---|---|
| AIS-08 / IAM-12/13: shared passcode, auth fails open | Databricks SSO per user; elsewhere OIDC sign-in, and the app refuses to run without it unless explicitly in local mode |
| LOG-04: audit actor hard-coded | Every write records the signed-in user's email |
| LOG-02: audit trigger failure ignored | Trigger creation is part of the schema transaction; if it fails, startup fails |
| LOG-13: logins not audited | `session.start` events are logged |
| IAM-14: plain env-var secrets | No database password; OAuth tokens minted per connection |
| CEK-03 / I&S-03: unverified TLS, public pooler | Lakebase requires TLS; access needs a Databricks identity with a Lakebase role |
| DSP-16 / DSP-17, BCR-08 | Lakebase encrypts at rest and has 7-day point-in-time restore; retention policy still to define |

Not done yet: per-object roles (everyone with access can edit), evidence file uploads, and a
retention policy for findings and answers.
