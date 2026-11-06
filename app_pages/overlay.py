import re
from datetime import date

import pandas as pd
import streamlit as st

from lib import overlay, ui
from lib.store import ORG_SYSTEM_ID, OVERLAY_RESPONSIBILITY, OVERLAY_STATUSES

st.title("ICF AI Control Overlay")
st.caption(
    "NIST AI RMF 1.0 control objectives from the ICF overlay for SP 800-37, assessed through your AI-CAIQ "
    "answers. Each objective's status comes from the AI-CAIQ questions on the AICM controls the AICM maps "
    "to it. Organization-owned objectives are answered once on the **Organization** profile and inherited "
    "by every AI system."
)

if not ui.store().has_table("overlay_objectives"):
    st.warning("The overlay tables don't exist yet. They are created when the Databricks App starts, "
               "so redeploy it once, then reload this page.")
    st.stop()

objectives = ui.overlay_objectives()
systems = ui.systems()
has_org = ORG_SYSTEM_ID in set(systems.system_id)

# ---------------------------------------------------------------- organization profile
if not has_org:
    st.info(
        "**No organization profile yet.** Create it to answer organization-owned objectives (and their "
        "AI-CAIQ questions) once, so every AI system inherits them. Until then, organization-owned "
        "objectives show as not assessed."
    )
    if st.button("Create the organization profile", type="primary"):
        ui.store().upsert_systems([{
            "system_id": ORG_SYSTEM_ID, "name": "Organization (common controls)", "component_type": "other",
            "role": None, "flag_internet": False, "flag_sensitive": False, "flag_untrusted": False,
            "flag_third_party": False, "source": "overlay",
            "notes": "Organization-level answers that every AI system inherits for the ICF AI overlay.",
        }], ui.actor())
        ui.audit("system.save", "ai_systems", ORG_SYSTEM_ID, "Organization profile for the ICF overlay")
        ui.refresh()
        st.rerun()

system = ui.system_picker("AI system (or the organization profile)", key="overlay_system")
if system is None:
    st.stop()
sid = system.system_id
is_org = sid == ORG_SYSTEM_ID

ids = (sid,) if is_org or not has_org else (sid, ORG_SYSTEM_ID)
direct = ui.overlay_assessments(ids)
org_answers = ui.answers(ORG_SYSTEM_ID) if has_org else pd.DataFrame()
result, ev = overlay.assess(
    objectives, ui.controls(), ui.questions(),
    sys_answers=ui.answers(sid), org_answers=org_answers,
    sys_direct=direct[direct.system_id == sid] if not direct.empty else direct,
    org_direct=direct[direct.system_id == ORG_SYSTEM_ID] if not direct.empty else direct,
    is_org=is_org,
)

if is_org:
    st.caption("Showing the organization-owned and shared objectives. Answer their AI-CAIQ questions on the "
               "**AI-CAIQ assessment** page with *Organization (common controls)* selected, or record a "
               "status directly below.")

# ---------------------------------------------------------------- summary
counts = result.effective_status.value_counts()
m = st.columns(5)
m[0].metric("Objectives", len(result))
m[1].metric("Met", int(counts.get("Met", 0)))
m[2].metric("Partially met / in progress", int(counts.get("Partially met", 0) + counts.get("In progress", 0)))
m[3].metric("Not met", int(counts.get("Not met", 0)))
m[4].metric("Not assessed", int(counts.get("Not assessed", 0) + counts.get("Needs direct assessment", 0)),
            help="Includes objectives with no AICM mapping, which need a status recorded directly")

by_fn = (result.assign(n=1).pivot_table(index="function", columns="effective_status", values="n",
                                        aggfunc="sum", fill_value=0)
         .reindex(["GOVERN", "MAP", "MEASURE", "MANAGE"]).dropna(how="all"))
by_fn = by_fn[[s for s in overlay.STATUS_ORDER if s in by_fn.columns]]
st.dataframe(by_fn, width="stretch")

# ---------------------------------------------------------------- filters
f1, f2, f3 = st.columns(3)
fn = f1.multiselect("Function", ["GOVERN", "MAP", "MEASURE", "MANAGE"])
resp = f2.multiselect("Responsibility", list(OVERLAY_RESPONSIBILITY), format_func=OVERLAY_RESPONSIBILITY.get)
stat = f3.multiselect("Status", [s for s in overlay.STATUS_ORDER if s in set(result.effective_status)])
view = result
if fn:
    view = view[view.function.isin(fn)]
if resp:
    view = view[view.responsibility.isin(resp)]
if stat:
    view = view[view.effective_status.isin(stat)]

# ---------------------------------------------------------------- editor
st.caption(f"{len(view)} objective(s). A status you record overrides the one computed from AI-CAIQ answers; "
           "clear it to go back to the computed status. Edit, then **Save changes**.")
EDIT = ["status", "notes"]
shown = view.assign(
    responsibility=view.responsibility.map(OVERLAY_RESPONSIBILITY),
    answers=view.apply(lambda r: f"{r.yes} Yes · {r.no} No · {r.na} NA · {r.unanswered} blank"
                       if r.questions else "No AICM mapping", axis=1),
)[["objective_id", "responsibility", "objective", "effective_status", "basis", "aicm_controls", "answers",
   "answers_from", "computed_status", "inherited_status", *EDIT]].reset_index(drop=True)
edited = st.data_editor(
    shown,
    key=f"overlay-{sid}-{fn}-{resp}-{stat}",
    hide_index=True, width="stretch", height=560, num_rows="fixed",
    disabled=[c for c in shown.columns if c not in EDIT],
    column_config={
        "objective_id": st.column_config.TextColumn("Objective", width="small", pinned=True),
        "responsibility": st.column_config.TextColumn("Owner", width="small"),
        "objective": st.column_config.TextColumn("Control objective", width="large"),
        "effective_status": st.column_config.TextColumn("Status", width="small"),
        "basis": st.column_config.TextColumn("Basis", width="small"),
        "aicm_controls": st.column_config.TextColumn("AICM controls", width="medium"),
        "answers": st.column_config.TextColumn("AI-CAIQ answers", width="medium"),
        "answers_from": st.column_config.TextColumn("Answered by", width="small",
                                                    help="Organization means inherited from the organization profile"),
        "computed_status": st.column_config.TextColumn("From AI-CAIQ", width="small"),
        "inherited_status": (None if is_org else
                             st.column_config.TextColumn("Organization status", width="small",
                                                         help="Recorded on the organization profile and inherited")),
        "status": st.column_config.SelectboxColumn("Recorded status", options=OVERLAY_STATUSES, width="small"),
        "notes": st.column_config.TextColumn("Assessor notes", width="large"),
    },
)


changed = ui.changed_rows(shown, edited, EDIT)
if st.button(f"Save changes ({len(changed)})", type="primary", disabled=not changed):
    rows = [{"objective_id": shown.objective_id.iloc[i], **vals} for i, vals in changed]
    ui.store().save_overlay_assessments(sid, rows, ui.actor())
    ui.audit("overlay.save", "overlay_assessments", sid,
             f"{len(rows)} objective(s): " + ", ".join(r["objective_id"] for r in rows[:50]))
    ui.refresh()
    st.toast(f"Saved {len(rows)} objective(s)")
    st.rerun()

# ---------------------------------------------------------------- evidence for one objective
st.divider()
st.subheader("Evidence for an objective")
oid = st.selectbox("Objective", view.objective_id.tolist() or result.objective_id.tolist(),
                   format_func=lambda o: f"{o} – {result.set_index('objective_id').objective[o][:90]}")
r = result.set_index("objective_id").loc[oid]
st.markdown(f"**{oid}** · {OVERLAY_RESPONSIBILITY[r.responsibility]}-owned · **{r.effective_status}** ({r.basis})")
st.write(r.objective)
e = ev[ev.objective_id == oid]
if e.empty:
    st.info("No AICM control maps to this objective, so record its status directly in the table above.")
else:
    st.dataframe(e[["control_id", "question_id", "question", "answer", "answer_from", "ssrm_owner", "implementation"]],
                 hide_index=True, width="stretch",
                 column_config={"question": st.column_config.TextColumn("Question", width="large"),
                                "implementation": st.column_config.TextColumn("Implementation", width="large"),
                                "answer_from": st.column_config.TextColumn("Answered by")})
note = r.notes or r.inherited_notes
if note:
    st.markdown(f"**Assessor notes:** {note}")

# ---------------------------------------------------------------- export
st.divider()
xlsx = overlay.build_workbook(result, ev, system["name"], date.today().isoformat())
safe = re.sub(r"[^A-Za-z0-9_-]+", "_", system["name"]).strip("_")[:60] or sid
fname = f"ICF_AI_Overlay_{safe}_{date.today().isoformat()}.xlsx"
st.download_button(
    "Download overlay status (.xlsx)", data=xlsx, file_name=fname,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    on_click=lambda: ui.audit("overlay.export", "overlay_assessments", sid, fname),
)
st.caption("Two sheets: status per objective, and the AI-CAIQ answers behind each one. "
           "Source: ICF AI Control Overlay (draft), derived from NIST AI RMF 1.0.")
