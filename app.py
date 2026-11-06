"""AI Governance Platform: CSA AICM v1.1.1 controls, AI-CAIQ self-assessment and STAR for AI export.

Runs as a Databricks App or anywhere Streamlit runs; data lives in Lakebase Postgres.
"""
import streamlit as st

from lib import ui
from lib.connection import running_as_databricks_app

st.set_page_config(page_title="AI Governance Platform", page_icon="🛡️", layout="wide")

user, source = ui.require_user()

try:
    ui.store()
except Exception as exc:  # show a readable error instead of a stack trace
    st.error(f"Could not connect to the Lakebase database: {exc}")
    st.stop()

pages = st.navigation(
    {
        "Overview": [
            st.Page("app_pages/dashboard.py", title="Dashboard", icon="📊", default=True),
        ],
        "Govern": [
            st.Page("app_pages/inventory.py", title="AI systems", icon="🗂️"),
            st.Page("app_pages/assessment.py", title="AI-CAIQ assessment", icon="📝"),
            st.Page("app_pages/export.py", title="STAR export", icon="📤"),
        ],
        "Reference": [
            st.Page("app_pages/controls.py", title="AICM controls", icon="📚"),
            st.Page("app_pages/audit.py", title="Audit log", icon="🧾"),
        ],
    }
)

with st.sidebar:
    st.caption(f"Signed in as **{user}**")
    st.caption("Databricks SSO" if running_as_databricks_app() else f"Auth: {source}")
    if source == "oidc":
        st.button("Sign out", on_click=st.logout)
    st.button("↻ Refresh data", on_click=ui.refresh, help="Reload inventory, findings and answers from Lakebase")
    if source == "unauthenticated-local":
        st.warning("Local mode without sign-in. Don't use this for shared deployments.")

pages.run()
