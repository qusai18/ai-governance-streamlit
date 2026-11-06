"""Parse the CSA AICM v1.1.x workbook and the AI-CAIQ questionnaire into plain records."""
from __future__ import annotations

import json
import re

import openpyxl

CONTROL_ID = re.compile(r"^[A-Z&]+-\d{2}$")
QUESTION_ID = re.compile(r"^[A-Z&]+-\d{2}\.\d+$")


def _s(v) -> str | None:
    if v is None:
        return None
    text = str(v).strip()
    return text or None


def _b(v) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "yes", "x", "1")


def _rows_by_control(ws, first_data_row: int, ncols: int) -> dict[str, list]:
    out = {}
    for r in range(first_data_row, ws.max_row + 1):
        cid = _s(ws.cell(r, 3).value)
        if cid and CONTROL_ID.match(cid):
            out[cid] = [ws.cell(r, c).value for c in range(1, ncols + 1)]
    return out


def _version(ws, default: str) -> str:
    try:
        meta = json.loads(ws.cell(1, 1).value)
        return meta.get("specification_version") or default
    except Exception:
        return default


def parse_aicm(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    main = wb["AICM"]
    version = _version(main, "1.1.1")
    impl = _rows_by_control(wb["Implementation Guidelines"], 4, 10)
    audit = _rows_by_control(wb["Auditing Guidelines"], 3, 9)
    maps = _rows_by_control(wb["Scope Applicability (Mappings)"], 4, 19)

    controls = []
    for cid, row in _rows_by_control(main, 4, 30).items():
        i = impl.get(cid, [None] * 10)
        a = audit.get(cid, [None] * 9)
        m = maps.get(cid, [None] * 19)
        controls.append({
            "control_id": cid,
            "domain": _s(row[0]),
            "domain_code": cid.rsplit("-", 1)[0],
            "title": _s(row[1]),
            "specification": _s(row[3]),
            "control_type": _s(row[4]),
            "owner_csp": _s(row[5]), "owner_mp": _s(row[6]), "owner_osp": _s(row[7]), "owner_ap": _s(row[8]),
            "arch_phys": _b(row[9]), "arch_network": _b(row[10]), "arch_compute": _b(row[11]),
            "arch_storage": _b(row[12]), "arch_app": _b(row[13]), "arch_data": _b(row[14]),
            "lc_preparation": _s(row[15]), "lc_development": _s(row[16]), "lc_evaluation": _s(row[17]),
            "lc_deployment": _s(row[18]), "lc_delivery": _s(row[19]), "lc_retirement": _s(row[20]),
            "threat_model_manipulation": _b(row[21]), "threat_data_poisoning": _b(row[22]),
            "threat_sensitive_data_disclosure": _b(row[23]), "threat_model_theft": _b(row[24]),
            "threat_service_failure": _b(row[25]), "threat_supply_chain": _b(row[26]),
            "threat_insecure_plugins": _b(row[27]), "threat_dos": _b(row[28]), "threat_governance": _b(row[29]),
            # Implementation Guidelines: Shared, MP, OSP, AP, AIC, CSP
            "impl_shared": _s(i[4]), "impl_mp": _s(i[5]), "impl_osp": _s(i[6]), "impl_ap": _s(i[7]),
            "impl_aic": _s(i[8]), "impl_csp": _s(i[9]),
            # Auditing Guidelines: AP, OSP, MP, AIC, CSP
            "audit_ap": _s(a[4]), "audit_osp": _s(a[5]), "audit_mp": _s(a[6]), "audit_aic": _s(a[7]),
            "audit_csp": _s(a[8]),
            # Mappings: AIUC-1, BSI AI C4, EU AI Act, ISO/IEC 42001, NIST AI RMF (+600-1)
            "map_aiuc1": _s(m[4]), "gap_aiuc1": _s(m[5]), "add_aiuc1": _s(m[6]),
            "map_bsi_c4": _s(m[7]), "gap_bsi_c4": _s(m[8]), "add_bsi_c4": _s(m[9]),
            "map_eu_ai_act": _s(m[10]), "gap_eu_ai_act": _s(m[11]), "add_eu_ai_act": _s(m[12]),
            "map_iso42001": _s(m[13]), "gap_iso42001": _s(m[14]), "add_iso42001": _s(m[15]),
            "map_nist_ai_rmf": _s(m[16]), "gap_nist_ai_rmf": _s(m[17]), "add_nist_ai_rmf": _s(m[18]),
            "aicm_version": version,
        })
    # The AICM sheet only names the domain on control rows; fill gaps from the previous row.
    last = None
    for c in controls:
        c["domain"] = c["domain"] or last
        last = c["domain"]
    return controls


CAIQ_SHEET_PREFIX = "AI-CAIQ"


def caiq_sheet(wb):
    for ws in wb.worksheets:
        if ws.title.startswith(CAIQ_SHEET_PREFIX):
            return ws
    raise ValueError("No AI-CAIQ sheet found in the workbook")


def parse_caiq(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = caiq_sheet(wb)
    version = ws.title.replace("AI-CAIQv", "") or "1.1.0"
    questions = []
    for r in range(3, ws.max_row + 1):
        qid = _s(ws.cell(r, 1).value)
        if not qid or not QUESTION_ID.match(qid):
            continue
        questions.append({
            "question_id": qid,
            "control_id": qid.rsplit(".", 1)[0],
            "question": _s(ws.cell(r, 2).value),
            "seq": len(questions) + 1,
            "caiq_version": version,
        })
    return questions
