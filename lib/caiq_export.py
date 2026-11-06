"""Write answers into the original CSA AI-CAIQ workbook (no rows, columns or sheets changed)."""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pandas as pd

from lib.aicm_parse import caiq_sheet

TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "AI-CAIQv1.1.0_template.xlsx"

# Column letters in the CSA template.
COL_ANSWER, COL_OWNER, COL_IMPL, COL_CUSTOMER = 3, 4, 5, 6


def _val(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def build_caiq_workbook(answers: pd.DataFrame, template: Path = TEMPLATE) -> tuple[bytes, int]:
    """Return (xlsx bytes, number of questions filled)."""
    by_q = {r.question_id: r for r in answers.itertuples()} if not answers.empty else {}
    wb = openpyxl.load_workbook(template)
    ws = caiq_sheet(wb)
    filled = 0
    for r in range(3, ws.max_row + 1):
        qid = ws.cell(r, 1).value
        rec = by_q.get(str(qid).strip()) if qid else None
        if rec is None:
            continue
        ws.cell(r, COL_ANSWER).value = _val(rec.answer)
        ws.cell(r, COL_OWNER).value = _val(rec.ssrm_owner)
        ws.cell(r, COL_IMPL).value = _val(rec.implementation)
        ws.cell(r, COL_CUSTOMER).value = _val(rec.customer_responsibility)
        filled += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), filled
