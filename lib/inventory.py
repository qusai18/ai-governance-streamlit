"""Import an `aicm-mapper` workspace export (components + per-control scanner observations)."""
from __future__ import annotations

import hashlib
from datetime import datetime

LIFECYCLE_PHASES = {
    1: "Preparation",
    2: "Development",
    3: "Evaluation/Validation",
    4: "Deployment",
    5: "Delivery",
    6: "Service Retirement",
}
LAYERS = ["Phys", "Network", "Compute", "Storage", "App", "Data"]


def _ts(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_workspace_export(data: dict) -> tuple[list[dict], list[dict]]:
    """Return (systems, findings) records ready for Store.upsert_system / upsert_findings."""
    if data.get("app") != "aicm-mapper" or "components" not in data:
        raise ValueError("This is not an aicm-mapper workspace export (missing app/components).")
    source = (data.get("source") or {}).get("repo") or "aicm-mapper import"

    systems = []
    for c in data["components"]:
        flags = c.get("flags") or {}
        systems.append({
            "system_id": c["id"],
            "name": c.get("name") or c["id"],
            "component_type": c.get("type"),
            "role": c.get("role"),
            "vendor": c.get("vendor"),
            "layers": ", ".join(c.get("layers") or []),
            "phases": ", ".join(str(p) for p in c.get("phases") or []),
            "flag_internet": bool(flags.get("internet")),
            "flag_sensitive": bool(flags.get("sensitive")),
            "flag_untrusted": bool(flags.get("untrusted")),
            "flag_third_party": bool(flags.get("thirdParty")),
            "notes": c.get("notes"),
            "source": source,
        })

    known = {s["system_id"] for s in systems}
    findings = []
    for key, st in (data.get("status") or {}).items():
        system_id, _, control_id = key.partition("|")
        if system_id not in known or not control_id:
            continue
        note = st.get("note") or ""
        # Deterministic id so re-importing the same file updates instead of duplicating.
        fid = "F-" + hashlib.sha1(key.encode()).hexdigest()[:12]
        not_applicable = "likely Not applicable" in note
        findings.append({
            "finding_id": fid,
            "system_id": system_id,
            "control_id": control_id,
            "note": note,
            "evidence": st.get("ev"),
            "observed_at": _ts(st.get("at")),
            "source": "Repo scan",
            "status": "Not applicable" if not_applicable else "Open",
        })
    return systems, findings
