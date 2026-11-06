"""ICF AI Control Overlay: NIST AI RMF 1.0 objectives assessed through the AICM / AI-CAIQ answers.

Each overlay objective is tagged O (organization), S (system) or O/S (shared). The AICM workbook maps
every AICM control to NIST AI RMF subcategories (column map_nist_ai_rmf), so an objective's status can
be computed from the AI-CAIQ answers on the controls mapped to it:

* O objectives use the organization's answers (the ORG system), inherited by every AI system.
* S objectives use the system's own answers.
* O/S objectives use the system's answer, or the organization's where the system has none.

An assessor can also record a direct status, which overrides the computed one. That is the only way
to assess objectives that no AICM control maps to.
No Streamlit import here, so it can be tested on its own.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pandas as pd

OVERLAY_VERSION = "ICF AI Control Overlay (draft, NIST AI RMF 1.0)"
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "icf_ai_overlay.csv"
_OBJ = re.compile(r"^\s*((?:GOVERN|MAP|MEASURE|MANAGE) \d+\.\d+)\s*$", re.M)

STATUS_ORDER = ["Met", "Partially met", "In progress", "Not met", "Not applicable", "Not assessed",
                "Needs direct assessment"]


def load_csv(path: Path = CSV_PATH) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["is_category"] = r["is_category"].strip().lower() == "true"
        r["seq"] = int(r["seq"])
        r["overlay_version"] = OVERLAY_VERSION
    return rows


def control_map(controls: pd.DataFrame) -> dict[str, list[str]]:
    """NIST AI RMF subcategory -> AICM control IDs, from the AICM's own mapping column."""
    out: dict[str, list[str]] = {}
    for cid, mapping in zip(controls.control_id, controls.map_nist_ai_rmf):
        for obj in _OBJ.findall(mapping or ""):
            out.setdefault(obj, []).append(cid)
    return {k: sorted(set(v)) for k, v in out.items()}


def _status(yes: int, no: int, na: int, blank: int) -> str:
    if yes + no + na == 0:
        return "Not assessed"
    if blank:
        return "In progress"
    if no == 0:
        return "Met" if yes else "Not applicable"
    return "Not met" if yes == 0 else "Partially met"


def evidence(objectives: pd.DataFrame, controls: pd.DataFrame, questions: pd.DataFrame,
             sys_answers: pd.DataFrame, org_answers: pd.DataFrame, is_org: bool) -> pd.DataFrame:
    """One row per (objective, AI-CAIQ question) with the answer that applies and where it came from."""
    cmap = control_map(controls)
    cols = ["question_id", "answer", "ssrm_owner", "implementation"]

    def by_question(df: pd.DataFrame) -> dict[str, dict]:
        if df.empty:
            return {}
        df = df[cols].astype("object").where(df[cols].notna(), None)
        return {r["question_id"]: r for r in df.to_dict("records") if r["answer"]}

    own, org = by_question(sys_answers), by_question(org_answers)
    q_by_control = {cid: g[["question_id", "question"]].to_dict("records")
                    for cid, g in questions.sort_values("seq").groupby("control_id")}
    rows = []
    for o in objectives.itertuples():
        for cid in cmap.get(o.objective_id, []):
            for q in q_by_control.get(cid, []):
                mine, theirs = own.get(q["question_id"]), org.get(q["question_id"])
                has_mine, has_theirs = mine is not None, theirs is not None
                if is_org or o.responsibility == "S":
                    pick, src = (mine, "System") if has_mine else (None, "")
                elif o.responsibility == "O":
                    pick, src = (theirs, "Organization") if has_theirs else (None, "")
                else:  # O/S: the system's own answer wins; otherwise inherit the organization's
                    pick, src = ((mine, "System") if has_mine else
                                 (theirs, "Organization") if has_theirs else (None, ""))
                if is_org and src:
                    src = "Organization"
                pick = pick or {}
                rows.append({
                    "objective_id": o.objective_id, "control_id": cid, "question_id": q["question_id"],
                    "question": q["question"], "answer": pick.get("answer"), "ssrm_owner": pick.get("ssrm_owner"),
                    "implementation": pick.get("implementation"), "answer_from": src,
                })
    return pd.DataFrame(rows, columns=["objective_id", "control_id", "question_id", "question", "answer",
                                       "ssrm_owner", "implementation", "answer_from"])


def assess(objectives: pd.DataFrame, controls: pd.DataFrame, questions: pd.DataFrame,
           sys_answers: pd.DataFrame, org_answers: pd.DataFrame,
           sys_direct: pd.DataFrame, org_direct: pd.DataFrame, is_org: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (one row per overlay objective with its status, the question-level evidence)."""
    objs = objectives[~objectives.is_category].copy()
    if is_org:  # the organization profile only answers what the organization owns or shares
        objs = objs[objs.responsibility.isin(["O", "O/S"])]
    ev = evidence(objs, controls, questions, sys_answers, org_answers, is_org)
    cmap = control_map(controls)

    def direct(df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        return {r.objective_id: (r.status, r.notes) for r in df.itertuples()}

    own_d, org_d = direct(sys_direct), direct(org_direct)
    rows = []
    for o in objs.itertuples():
        e = ev[ev.objective_id == o.objective_id]
        yes, no, na = (int((e.answer == v).sum()) for v in ("Yes", "No", "NA"))
        blank = int(e.answer.isna().sum())
        computed = _status(yes, no, na, blank) if len(e) else "Needs direct assessment"
        froms = sorted(set(e.answer_from) - {""})
        status, notes = own_d.get(o.objective_id, (None, None))
        inherited_status, inherited_notes = (None, None)
        if not is_org and o.responsibility in ("O", "O/S"):
            inherited_status, inherited_notes = org_d.get(o.objective_id, (None, None))
        if pd.notna(status) and status:
            effective, basis = status, "Assessor"
        elif pd.notna(inherited_status) and inherited_status:
            effective, basis = inherited_status, "Assessor (organization)"
        else:
            effective, basis = computed, "AI-CAIQ answers" if len(e) else "—"
        rows.append({
            "objective_id": o.objective_id, "function": o.function, "responsibility": o.responsibility,
            "objective": o.objective, "aicm_controls": ", ".join(cmap.get(o.objective_id, [])),
            "questions": len(e), "yes": yes, "no": no, "na": na, "unanswered": blank,
            "answers_from": " + ".join(froms), "computed_status": computed,
            "inherited_status": inherited_status if pd.notna(inherited_status) else None,
            "inherited_notes": inherited_notes if pd.notna(inherited_notes) else None,
            "status": status if pd.notna(status) else None, "notes": notes if pd.notna(notes) else None,
            "effective_status": effective, "basis": basis,
        })
    return pd.DataFrame(rows), ev


def build_workbook(result: pd.DataFrame, ev: pd.DataFrame, system_name: str, as_of: str) -> bytes:
    """An .xlsx with the overlay status per objective and the AI-CAIQ evidence behind it."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    resp = {"O": "Organization", "S": "System", "O/S": "Shared"}
    wb = Workbook()
    ws = wb.active
    ws.title = "Overlay status"
    ws.append([OVERLAY_VERSION])
    ws.append([f"AI system: {system_name}", f"As of {as_of}"])
    ws.append([])
    head = ["Objective", "Function", "Responsibility", "Control objective", "Status", "Basis",
            "AICM controls", "AI-CAIQ questions", "Yes", "No", "NA", "Unanswered", "Answers from",
            "Status from AI-CAIQ", "Assessor notes"]
    ws.append(head)
    for r in result.itertuples():
        ws.append([r.objective_id, r.function, resp.get(r.responsibility, r.responsibility), r.objective,
                   r.effective_status, r.basis, r.aicm_controls, r.questions, r.yes, r.no, r.na, r.unanswered,
                   r.answers_from, r.computed_status, r.notes or r.inherited_notes])
    ev_ws = wb.create_sheet("AI-CAIQ evidence")
    ev_ws.append(["Objective", "AICM control", "Question ID", "Question", "Answer", "SSRM owner",
                  "Implementation description", "Answer from"])
    for r in ev.itertuples():
        ev_ws.append([r.objective_id, r.control_id, r.question_id, r.question, r.answer, r.ssrm_owner,
                      r.implementation, r.answer_from])

    bold, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3864")
    ws["A1"].font = Font(bold=True, size=13)
    for sheet, row, widths in ((ws, 4, [13, 10, 13, 70, 16, 20, 30, 10, 6, 6, 6, 11, 22, 20, 40]),
                               (ev_ws, 1, [13, 12, 12, 70, 8, 22, 50, 14])):
        for i, w in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(i)].width = w
            c = sheet.cell(row=row, column=i)
            c.font, c.fill = bold, fill
        sheet.freeze_panes = sheet.cell(row=row + 1, column=2)
        for line in sheet.iter_rows(min_row=row + 1):
            for c in line:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
