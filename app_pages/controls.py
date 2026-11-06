import streamlit as st

from lib import ui

st.title("AICM control library")
st.caption("CSA AI Controls Matrix v1.1.1: 18 domains, with implementation and auditing guidelines and framework mappings.")

c = ui.controls()
q = ui.questions()

THREATS = {
    "threat_model_manipulation": "Model manipulation",
    "threat_data_poisoning": "Data poisoning",
    "threat_sensitive_data_disclosure": "Sensitive data disclosure",
    "threat_model_theft": "Model theft",
    "threat_service_failure": "Model/service failure",
    "threat_supply_chain": "Insecure supply chain",
    "threat_insecure_plugins": "Insecure apps/plugins",
    "threat_dos": "Denial of service",
    "threat_governance": "Loss of governance/compliance",
}
LAYERS = {"arch_phys": "Phys", "arch_network": "Network", "arch_compute": "Compute",
          "arch_storage": "Storage", "arch_app": "App", "arch_data": "Data"}
FRAMEWORKS = {"eu_ai_act": "EU AI Act", "iso42001": "ISO/IEC 42001", "nist_ai_rmf": "NIST AI RMF + 600-1",
              "aiuc1": "AIUC-1", "bsi_c4": "BSI AI C4"}

with st.sidebar:
    st.subheader("Filters")
    doms = c[["domain_code", "domain"]].drop_duplicates().sort_values("domain_code")
    dom_label = dict(zip(doms.domain_code, doms.domain))
    sel_dom = st.multiselect("Domain", doms.domain_code.tolist(), format_func=lambda d: f"{d} – {dom_label[d]}")
    sel_type = st.multiselect("Control type", sorted(c.control_type.dropna().unique()))
    sel_threat = st.multiselect("Threat category", list(THREATS), format_func=THREATS.get)
    sel_layer = st.multiselect("Architecture layer", list(LAYERS), format_func=LAYERS.get)
    fw = st.selectbox("Framework gap", ["(any)"] + list(FRAMEWORKS), format_func=lambda k: FRAMEWORKS.get(k, k))
    gap = st.multiselect("Gap level", ["No Gap", "Partial Gap", "Full Gap"], disabled=fw == "(any)")

text = st.text_input("Search", placeholder="Search control ID, title or specification")
v = c
if sel_dom:
    v = v[v.domain_code.isin(sel_dom)]
if sel_type:
    v = v[v.control_type.isin(sel_type)]
if sel_threat:
    v = v[v[sel_threat].fillna(False).any(axis=1)]
if sel_layer:
    v = v[v[sel_layer].fillna(False).any(axis=1)]
if fw != "(any)" and gap:
    v = v[v[f"gap_{fw}"].isin(gap)]
if text:
    t = text.lower()
    v = v[v.control_id.str.lower().str.contains(t, regex=False)
          | v.title.str.lower().str.contains(t, regex=False)
          | v.specification.fillna("").str.lower().str.contains(t, regex=False)]

st.caption(f"{len(v)} of {len(c)} controls")
event = st.dataframe(
    v[["control_id", "domain", "title", "control_type", "gap_eu_ai_act", "gap_iso42001", "gap_nist_ai_rmf"]],
    hide_index=True, width="stretch", height=380, on_select="rerun", selection_mode="single-row",
    column_config={"control_id": "ID", "gap_eu_ai_act": "EU AI Act gap", "gap_iso42001": "ISO 42001 gap",
                   "gap_nist_ai_rmf": "NIST AI RMF gap"},
)
rows = event.selection.rows
if not rows:
    st.info("Select a control to see its guidance, mappings and AI-CAIQ questions.")
    st.stop()

ctl = v.iloc[rows[0]]
st.subheader(f"{ctl.control_id} · {ctl.title}")
st.caption(f"{ctl.domain} · {ctl.control_type}")
st.write(ctl.specification)

t_own, t_impl, t_audit, t_map, t_q = st.tabs(
    ["Applicability", "Implementation", "Auditing", "Framework mappings", "AI-CAIQ questions"])
with t_own:
    st.markdown("**Typical owners**")
    st.table({"Actor": ["Cloud/AI processing infrastructure", "Model", "Orchestrated services", "Application"],
              "Owner": [ctl.owner_csp, ctl.owner_mp, ctl.owner_osp, ctl.owner_ap]})
    st.markdown("**Architecture layers:** " + (", ".join(n for k, n in LAYERS.items() if ctl[k]) or "—"))
    st.markdown("**Threat categories:** " + (", ".join(n for k, n in THREATS.items() if ctl[k]) or "—"))
    st.markdown("**Lifecycle relevance**")
    st.table({"Phase": ["Preparation", "Development", "Evaluation/Validation", "Deployment", "Delivery", "Retirement"],
              "Relevant activities": [ctl.lc_preparation, ctl.lc_development, ctl.lc_evaluation,
                                      ctl.lc_deployment, ctl.lc_delivery, ctl.lc_retirement]})
with t_impl:
    for col, label in [("impl_shared", "Shared (all providers)"), ("impl_mp", "Model Provider"),
                       ("impl_osp", "Orchestrated Service Provider"), ("impl_ap", "Application Provider"),
                       ("impl_aic", "AI Customer"), ("impl_csp", "Cloud Service Provider")]:
        with st.expander(label, expanded=col == "impl_shared"):
            st.markdown(ctl[col] or "_None_")
with t_audit:
    for col, label in [("audit_ap", "Application Provider"), ("audit_osp", "Orchestrated Service Provider"),
                       ("audit_mp", "Model Provider"), ("audit_aic", "AI Customer"),
                       ("audit_csp", "Cloud Service Provider")]:
        with st.expander(label, expanded=col == "audit_ap"):
            st.markdown(ctl[col] or "_None_")
with t_map:
    st.table({
        "Framework": list(FRAMEWORKS.values()),
        "Mapped requirements": [ctl[f"map_{k}"] for k in FRAMEWORKS],
        "Gap": [ctl[f"gap_{k}"] for k in FRAMEWORKS],
        "Addendum": [ctl[f"add_{k}"] for k in FRAMEWORKS],
    })
with t_q:
    st.dataframe(q[q.control_id == ctl.control_id][["question_id", "question"]], hide_index=True, width="stretch")
    f = ui.findings()
    f = f[f.control_id == ctl.control_id] if not f.empty else f
    if not f.empty:
        names = dict(zip(ui.systems().system_id, ui.systems().name))
        st.markdown("**Findings across AI systems**")
        st.dataframe(f.assign(system=f.system_id.map(names))[["system", "status", "note"]],
                     hide_index=True, width="stretch")
