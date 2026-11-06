import pandas as pd
import streamlit as st

from lib import rules, ui
from lib.store import CAIQ_ANSWERS, ROLES, SSRM_OWNERS

EDIT_COLS = ["answer", "ssrm_owner", "implementation", "customer_responsibility"]

st.title("AI-CAIQ self-assessment")
st.caption(
    "Answer each question Yes / No / NA, name the SSRM owner, and describe the implementation with evidence. "
    "Rules from CSA's *Filling in the AI-CAIQ* guide are checked as you go."
)

system = ui.system_picker()
if system is None:
    st.stop()
sid = system.system_id
role = system.role

base = rules.assess(ui.assessment_frame(sid))
controls = ui.controls().set_index("control_id")
fnd = ui.findings(sid)
open_f = fnd[fnd.status.isin(["Open", "In remediation"])] if not fnd.empty else fnd
f_count = open_f.groupby("control_id").size().to_dict() if not open_f.empty else {}
base["open_findings"] = base.control_id.map(f_count).fillna(0).astype(int)

# ---------------------------------------------------------------- progress
total = len(base)
done = int(base.answer.notna().sum())
blockers = int((base.errors > 0).sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Answered", f"{done} / {total}")
m2.metric("Yes / No / NA", f"{(base.answer == 'Yes').sum()} / {(base.answer == 'No').sum()} / {(base.answer == 'NA').sum()}")
m3.metric("STAR blockers", blockers, help="Missing answer or owner, Yes with Not Determined, or NA without justification")
m4.metric("Role", f"{role} – {ROLES.get(role, '?')}" if role else "not set")
st.progress(done / total if total else 0.0)

# ---------------------------------------------------------------- filters
domains = base[["domain_code", "domain"]].drop_duplicates().sort_values("domain_code")
dom_labels = dict(zip(domains.domain_code, domains.domain))
f1, f2, f3 = st.columns([2, 1, 2])
dom = f1.selectbox("Domain", ["All"] + domains.domain_code.tolist(),
                   format_func=lambda d: "All domains" if d == "All" else f"{d} – {dom_labels[d]}")
show = f2.selectbox("Show", ["All", "Unanswered", "STAR blockers", "Warnings", "Has open findings"])
text = f3.text_input("Search questions", placeholder="e.g. model card, red team, encryption")

view = base
if dom != "All":
    view = view[view.domain_code == dom]
if show == "Unanswered":
    view = view[view.answer.isna()]
elif show == "STAR blockers":
    view = view[view.errors > 0]
elif show == "Warnings":
    view = view[view.warnings > 0]
elif show == "Has open findings":
    view = view[view.open_findings > 0]
if text:
    t = text.lower()
    view = view[view.question.str.lower().str.contains(t, regex=False)
                | view.question_id.str.lower().str.contains(t, regex=False)]

# ---------------------------------------------------------------- owner suggestions
with st.expander("Fill blank owners from the AICM", expanded=False):
    st.markdown(
        f"Uses the AICM *Typical Control Applicability and Owners* column for your role (**{role or 'not set'}**) "
        "to fill **only blank** SSRM owners in the questions shown below. Review before submitting."
    )
    sugg = []
    if role in rules.ROLE_OWNER_COLUMN:
        for r in view[view.ssrm_owner.isna()].itertuples():
            owner = rules.suggested_owner(controls.loc[r.control_id], role) if r.control_id in controls.index else None
            if owner:
                sugg.append({"question_id": r.question_id, "answer": r.answer, "ssrm_owner": owner,
                             "implementation": r.implementation,
                             "customer_responsibility": r.customer_responsibility})
    else:
        st.caption("The AICM has owner columns for CSP, MP, OSP and AP roles only.")
    if st.button(f"Fill {len(sugg)} owner(s) and save", disabled=not sugg):
        ui.store().save_answers(sid, sugg, ui.actor())
        ui.audit("caiq.owners.suggest", "caiq_answers", sid, f"{len(sugg)} owners from AICM ({role})")
        ui.refresh()
        st.rerun()

# ---------------------------------------------------------------- editor
st.caption(f"{len(view)} question(s) shown. Edit cells, then **Save changes**.")
shown = view[["question_id", "control_id", "question", *EDIT_COLS, "open_findings", "issues"]].reset_index(drop=True)
editor_key = f"caiq-{sid}-{dom}-{show}-{text}"
edited = st.data_editor(
    shown,
    key=editor_key,
    hide_index=True,
    width="stretch",
    height=560,
    num_rows="fixed",
    disabled=["question_id", "control_id", "question", "open_findings", "issues"],
    column_config={
        "question_id": st.column_config.TextColumn("ID", width="small", pinned=True),
        "control_id": None,
        "question": st.column_config.TextColumn("Question", width="large"),
        "answer": st.column_config.SelectboxColumn("Answer", options=CAIQ_ANSWERS, width="small"),
        "ssrm_owner": st.column_config.SelectboxColumn("SSRM owner", options=SSRM_OWNERS, width="medium"),
        "implementation": st.column_config.TextColumn(
            "Implementation description", width="large",
            help="How the control is implemented, with evidence. Required to justify NA."),
        "customer_responsibility": st.column_config.TextColumn("Customer responsibilities", width="large"),
        "open_findings": st.column_config.NumberColumn("Findings", width="small"),
        "issues": st.column_config.TextColumn("Checks", width="large"),
    },
)


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    return df[EDIT_COLS].astype("object").where(df[EDIT_COLS].notna(), None).apply(
        lambda col: col.map(lambda v: v.strip() or None if isinstance(v, str) else v))


before, after = _norm(shown), _norm(edited)
changed_mask = (before.fillna("\0") != after.fillna("\0")).any(axis=1)
changes = edited[changed_mask]

s1, s2 = st.columns([1, 3])
if s1.button(f"Save changes ({len(changes)})", type="primary", disabled=changes.empty):
    rows = [{"question_id": r.question_id, **after.loc[i].to_dict()} for i, r in changes.iterrows()]
    ui.store().save_answers(sid, rows, ui.actor())
    ui.audit("caiq.answers.save", "caiq_answers", sid,
             f"{len(rows)} answer(s): " + ", ".join(r["question_id"] for r in rows[:50]))
    ui.refresh()
    st.toast(f"Saved {len(rows)} answer(s)")
    st.rerun()
if not changes.empty:
    issues = sum(len([i for i in rules.check_answer(r.answer, r.ssrm_owner, r.implementation) if i[0] == "error"])
                 for r in after[changed_mask].itertuples())
    s2.caption(f"Unsaved edits to {len(changes)} question(s)" + (f", {issues} STAR blocker(s) among them." if issues else "."))

# ---------------------------------------------------------------- guidance
st.divider()
st.subheader("Control guidance")
cids = view.control_id.drop_duplicates().tolist() or base.control_id.drop_duplicates().tolist()
cid = st.selectbox("Control", cids, format_func=lambda c: f"{c} – {controls.loc[c, 'title']}" if c in controls.index else c)
if cid in controls.index:
    c = controls.loc[cid]
    st.markdown(f"**{cid} · {c.title}** · {c.control_type}")
    st.write(c.specification)
    role_impl = {"MP": "impl_mp", "OSP": "impl_osp", "AP": "impl_ap", "AIC": "impl_aic", "CSP": "impl_csp"}.get(role)
    role_audit = {"MP": "audit_mp", "OSP": "audit_osp", "AP": "audit_ap", "AIC": "audit_aic", "CSP": "audit_csp"}.get(role)
    g1, g2 = st.tabs([f"Implementation guidance ({role or 'shared'})", f"Auditing guidance ({role or 'AP'})"])
    with g1:
        st.markdown(c[role_impl] if role_impl and c[role_impl] else c.impl_shared or "_None_")
        with st.expander("Shared guidance (all providers)"):
            st.markdown(c.impl_shared or "_None_")
    with g2:
        st.markdown(c[role_audit] if role_audit and c[role_audit] else c.audit_ap or "_None_")
    cf = open_f[open_f.control_id == cid] if not open_f.empty else open_f
    if not cf.empty:
        st.markdown("**Open findings for this control**")
        for r in cf.itertuples():
            st.warning(f"{r.note}\n\n*Evidence:* {r.evidence or '—'}")
