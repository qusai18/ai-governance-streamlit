"""Agent Action Gate: interactive walkthrough of the guardrail lifecycle for AI agents.

The page is a self-contained HTML/JavaScript app (data/action_gate.html), copied from
github.com/qusai18/agent-action-gate. Its decision log is kept in the viewer's browser,
not in Lakebase, so it does not appear in the Audit log.
"""
from lib.ui import DATA

import streamlit as st

# A fixed height, scrolled inside the frame: height="content" only ever grows (it measures the
# frame's own document height), which left thousands of pixels of blank space after a run.
st.iframe(DATA / "action_gate.html", height=1100)
