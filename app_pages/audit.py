import streamlit as st

from lib import ui

st.title("Audit log")
st.caption("Append-only record of sign-ins and every change made in the app. "
           "A database trigger rejects updates, deletes and truncation of this table.")

log = ui.store().audit_log(limit=2000)
if log.empty:
    st.info("No events yet.")
    st.stop()

c1, c2 = st.columns(2)
actors = c1.multiselect("Actor", sorted(log.actor.unique()))
actions = c2.multiselect("Action", sorted(log.action.unique()))
v = log
if actors:
    v = v[v.actor.isin(actors)]
if actions:
    v = v[v.action.isin(actions)]
st.dataframe(v[["event_ts", "actor", "auth_source", "action", "entity", "entity_id", "detail"]],
             hide_index=True, width="stretch", height=600)
st.download_button("Download CSV", v.to_csv(index=False).encode("utf-8"), "aigov_audit_log.csv", "text/csv")
