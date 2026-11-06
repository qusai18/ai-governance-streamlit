import re
from datetime import date

import streamlit as st

from lib import rules, ui
from lib.caiq_export import build_caiq_workbook

st.title("STAR for AI Level 1 export")
st.caption("Download the completed AI-CAIQ in the original CSA format, ready to attach to the STAR submission form.")

system = ui.system_picker()
if system is None:
    st.stop()
sid = system.system_id

df = rules.assess(ui.assessment_frame(sid))
errors = df[df.errors > 0]
warnings = df[(df.errors == 0) & (df.warnings > 0)]

c1, c2, c3 = st.columns(3)
c1.metric("Questions answered", f"{int(df.answer.notna().sum())} / {len(df)}")
c2.metric("STAR blockers", len(errors))
c3.metric("Warnings", len(warnings))

if errors.empty:
    st.success("Every question has an answer and an SSRM owner, and the CSA decision rules pass.")
else:
    st.error(f"{len(errors)} question(s) would block a STAR Level 1 submission. Fix them on the "
             "**AI-CAIQ assessment** page (filter: *STAR blockers*).")
with st.expander(f"Issues ({len(errors) + len(warnings)})", expanded=not errors.empty):
    st.dataframe(
        df[(df.errors > 0) | (df.warnings > 0)][["question_id", "answer", "ssrm_owner", "issues"]],
        hide_index=True, width="stretch",
        column_config={"issues": st.column_config.TextColumn("Checks", width="large")},
    )

xlsx, filled = build_caiq_workbook(df)
safe = re.sub(r"[^A-Za-z0-9_-]+", "_", system["name"]).strip("_")[:60] or sid
fname = f"AI-CAIQv1.1.0_{safe}_{date.today().isoformat()}.xlsx"


def _log():
    ui.audit("caiq.export", "caiq_answers", sid,
             f"{fname}: {filled} questions, {len(errors)} blockers, {len(warnings)} warnings")


st.download_button(
    "Download AI-CAIQ (.xlsx)",
    data=xlsx,
    file_name=fname,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    on_click=_log,
)
if not errors.empty:
    st.caption("You can download a draft now; CSA requires every Answer and SSRM ownership cell to be filled.")

st.divider()
st.subheader("Submission checklist")
st.markdown(
    """
1. **Keep the original CSA format**: this export only fills columns C–F; don't add or remove rows, columns or sheets.
2. **Have one reviewer sweep** columns C–F for consistent style and choices.
3. **Gather submission details**: organisation name, URL and description; service name, URL and description;
   primary and backup point of contact with emails; region.
4. **Sign in to the CSA STAR platform** with your work email, open the STAR submission form, choose
   *Self-assessment* as the registry entry type and *AI-CAIQ* as the specification, and attach this `.xlsx`.
5. **Confirm** from the email CSA sends, then pick (or create) your organisation and cloud service.
   Listings usually appear within one business day.
6. For **Valid-AI-ted** (free for CSA members), give detailed answers in columns E and F.
"""
)
