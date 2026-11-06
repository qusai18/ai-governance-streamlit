import altair as alt
import pandas as pd
import streamlit as st

from lib import rules, ui
from lib.store import ORG_SYSTEM_ID

st.title("AI governance dashboard")
st.caption("CSA AI Controls Matrix v1.1.1 · AI-CAIQ v1.1.0 self-assessment status across your AI systems")

systems = ui.systems()
# The organization profile holds inherited answers for the ICF overlay; it is not an AI system.
systems = systems[systems.system_id != ORG_SYSTEM_ID]
questions = ui.questions()
total_q = len(questions)
all_answers = ui.answers()
all_answers = all_answers[all_answers.system_id != ORG_SYSTEM_ID] if not all_answers.empty else all_answers
all_findings = ui.findings()
open_findings = all_findings[all_findings.status.isin(["Open", "In remediation"])] if not all_findings.empty else all_findings

c1, c2, c3, c4 = st.columns(4)
c1.metric("AI systems", len(systems))
c2.metric("AICM controls", len(ui.controls()))
c3.metric("Open findings", len(open_findings))
answered = int(all_answers.answer.notna().sum()) if not all_answers.empty else 0
c4.metric("CAIQ answers", f"{answered:,} / {total_q * max(len(systems), 1):,}")

if systems.empty:
    st.info("Start on the **AI systems** page: add a system or import your aicm-mapper workspace export.")
    st.stop()

# ---------------------------------------------------------------- portfolio
rows = []
for s in systems.itertuples():
    df = rules.assess(ui.assessment_frame(s.system_id))
    f = all_findings[all_findings.system_id == s.system_id] if not all_findings.empty else all_findings
    rows.append({
        "AI system": s.name,
        "Role": s.role,
        "Answered": int(df.answer.notna().sum()),
        "Yes": int((df.answer == "Yes").sum()),
        "No": int((df.answer == "No").sum()),
        "NA": int((df.answer == "NA").sum()),
        "STAR blockers": int((df.errors > 0).sum()),
        "Open findings": int(f.status.isin(["Open", "In remediation"]).sum()) if not f.empty else 0,
    })
portfolio = pd.DataFrame(rows)
portfolio["Progress"] = portfolio.Answered / total_q
st.subheader("Portfolio")
st.dataframe(
    portfolio,
    hide_index=True,
    width="stretch",
    column_config={
        "Progress": st.column_config.ProgressColumn("Progress", format="percent", min_value=0, max_value=1),
        "STAR blockers": st.column_config.NumberColumn(help="Questions that would block a STAR Level 1 submission"),
    },
)

# ---------------------------------------------------------------- one system
st.subheader("By domain")
system = ui.system_picker()
if system is None:
    st.stop()
df = rules.assess(ui.assessment_frame(system.system_id))
by_dom = (
    df.assign(answered=df.answer.notna(), yes=df.answer == "Yes", no=df.answer == "No")
    .groupby(["domain_code", "domain"], as_index=False)
    .agg(questions=("question_id", "count"), answered=("answered", "sum"), yes=("yes", "sum"), no=("no", "sum"))
)
by_dom["Completion"] = by_dom.answered / by_dom.questions
by_dom["Yes share of answered Yes/No"] = (by_dom.yes / (by_dom.yes + by_dom.no)).fillna(0)

left, right = st.columns(2)
with left:
    st.markdown("**Completion by domain**")
    chart = (
        alt.Chart(by_dom)
        .mark_bar()
        .encode(
            x=alt.X("Completion:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("domain:N", sort="-x", title=None),
            tooltip=["domain", "questions", "answered", alt.Tooltip("Completion:Q", format=".0%")],
        )
        .properties(height=460)
    )
    st.altair_chart(chart, width="stretch")
with right:
    st.markdown("**Answer mix by domain**")
    mix = df.assign(answer=df.answer.fillna("Unanswered")).groupby(["domain", "answer"], as_index=False).size()
    chart = (
        alt.Chart(mix)
        .mark_bar()
        .encode(
            x=alt.X("size:Q", stack="normalize", axis=alt.Axis(format="%"), title="Share of questions"),
            y=alt.Y("domain:N", title=None),
            color=alt.Color(
                "answer:N",
                scale=alt.Scale(domain=["Yes", "No", "NA", "Unanswered"],
                                range=["#2e7d32", "#c62828", "#78909c", "#e0e0e0"]),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["domain", "answer", "size"],
        )
        .properties(height=460)
    )
    st.altair_chart(chart, width="stretch")

f = ui.findings(system.system_id)
st.subheader(f"Findings for {system['name']}")
if f.empty:
    st.caption("No findings recorded for this system.")
else:
    ctrl = ui.controls()[["control_id", "domain", "title"]]
    f = f.merge(ctrl, on="control_id", how="left")
    st.dataframe(
        f[["control_id", "title", "status", "note", "evidence"]].sort_values(["status", "control_id"]),
        hide_index=True, width="stretch",
    )
