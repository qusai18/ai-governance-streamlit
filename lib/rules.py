"""CSA AI-CAIQ completion rules ("Filling in the AI-CAIQ: Instructions and Recommendations",
and the STAR for AI Level 1 Submission Guide)."""
from __future__ import annotations

import re

import pandas as pd

ND = "Not Determined"

# AICM "Typical Control Applicability and Owners" text -> AI-CAIQ SSRM dropdown value.
_ABBREV = {
    "CSP": "Owned by CSP", "MP": "Owned by MP", "OSP": "Owned by OSP", "AP": "Owned by AP",
    "AIC": "Owned by AIC", "Shared CSP-MP": "Shared CSP-MP", "Shared MP-OSP": "Shared MP-OSP",
    "Shared OSP-AP": "Shared OSP-AP", "Shared AP-AIC": "Shared AP-AIC",
}
ROLE_OWNER_COLUMN = {"CSP": "owner_csp", "MP": "owner_mp", "OSP": "owner_osp", "AP": "owner_ap"}


def aicm_owner_to_ssrm(text: str | None) -> str | None:
    if not text or text.strip().upper() == "N/A":
        return None
    if "supply chain" in text.lower():
        return "Shared across the supply chain"
    m = re.search(r"\(([^)]+)\)\s*$", text.strip())
    if m:
        return _ABBREV.get(m.group(1).strip())
    return None


def suggested_owner(control: dict | pd.Series, role: str | None) -> str | None:
    col = ROLE_OWNER_COLUMN.get(role or "")
    return aicm_owner_to_ssrm(control.get(col)) if col else None


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""


def check_answer(answer, owner, implementation) -> list[tuple[str, str]]:
    """Return a list of (severity, message); severity is 'error' (blocks STAR) or 'warning'."""
    issues: list[tuple[str, str]] = []
    if _blank(answer):
        issues.append(("error", "Answer (Yes/No/NA) is required for STAR submission"))
    if _blank(owner):
        issues.append(("error", "SSRM control ownership is required for STAR submission"))
    if answer == "Yes" and owner == ND:
        issues.append(("error", "A Yes answer must name at least one owner (Not Determined is not allowed)"))
    if answer == "NA" and _blank(implementation):
        issues.append(("error", "NA needs a short justification in the implementation description"))
    if answer == "No" and owner == ND:
        issues.append(("warning", "No answer: name the owner responsible for remediation if you can"))
    if answer in ("Yes", "No") and _blank(implementation):
        issues.append(("warning", "Describe the implementation and cite evidence (recommended)"))
    return issues


def issues_text(issues: list[tuple[str, str]]) -> str:
    return "; ".join(("⛔ " if s == "error" else "⚠️ ") + m for s, m in issues)


def assess(df: pd.DataFrame) -> pd.DataFrame:
    """Add `errors`, `warnings`, `issues` columns to a frame with answer/ssrm_owner/implementation."""
    out = df.copy()
    res = [check_answer(r.answer, r.ssrm_owner, r.implementation) for r in out.itertuples()]
    out["errors"] = [sum(1 for s, _ in i if s == "error") for i in res]
    out["warnings"] = [sum(1 for s, _ in i if s == "warning") for i in res]
    out["issues"] = [issues_text(i) for i in res]
    return out
