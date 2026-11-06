import json
import re

import pandas as pd
import streamlit as st

from lib import ui
from lib.inventory import LAYERS, LIFECYCLE_PHASES, parse_workspace_export
from lib.store import COMPONENT_TYPES, FINDING_STATUSES, ROLES, new_id

st.title("AI systems")
st.caption("Inventory of AI products, services and infrastructure under governance, with control findings.")

systems = ui.systems()
tab_list, tab_edit, tab_findings, tab_import = st.tabs(["Inventory", "Add / edit", "Findings", "Import"])

# ---------------------------------------------------------------- inventory
with tab_list:
    if systems.empty:
        st.info("No AI systems yet. Use **Add / edit** or **Import**.")
    else:
        view = systems.copy()
        view["phases"] = view.phases.fillna("").apply(
            lambda p: ", ".join(LIFECYCLE_PHASES.get(int(x), x) for x in re.findall(r"\d+", p)))
        st.dataframe(
            view[["name", "system_id", "component_type", "role", "vendor", "layers", "phases",
                  "flag_internet", "flag_sensitive", "flag_untrusted", "flag_third_party",
                  "updated_at", "updated_by"]],
            hide_index=True, width="stretch",
            column_config={
                "flag_internet": st.column_config.CheckboxColumn("Internet-facing"),
                "flag_sensitive": st.column_config.CheckboxColumn("Sensitive data"),
                "flag_untrusted": st.column_config.CheckboxColumn("Untrusted input"),
                "flag_third_party": st.column_config.CheckboxColumn("Third party"),
            },
        )

# ---------------------------------------------------------------- add / edit
with tab_edit:
    options = ["__new__"] + systems.system_id.tolist()
    names = dict(zip(systems.system_id, systems.name))
    pick = st.selectbox("System", options, format_func=lambda i: "➕ New AI system" if i == "__new__" else names[i])
    rec = {} if pick == "__new__" else systems[systems.system_id == pick].iloc[0].to_dict()

    with st.form(f"system-{pick}"):
        name = st.text_input("Name *", rec.get("name", ""))
        c1, c2, c3 = st.columns(3)
        ctype = c1.selectbox("Component type", COMPONENT_TYPES,
                             index=COMPONENT_TYPES.index(rec["component_type"])
                             if rec.get("component_type") in COMPONENT_TYPES else 0)
        role_keys = list(ROLES)
        role = c2.selectbox("AICM role", role_keys, format_func=lambda r: f"{r} – {ROLES[r]}",
                            index=role_keys.index(rec["role"]) if rec.get("role") in role_keys else 3,
                            help="Your organisation's role for this component in the AICM shared security model.")
        vendor = c3.text_input("Vendor / source", rec.get("vendor") or "")
        cur_layers = [x.strip() for x in (rec.get("layers") or "").split(",") if x.strip() in LAYERS]
        layers = st.multiselect("Architecture layers", LAYERS, default=cur_layers)
        cur_phases = [int(x) for x in re.findall(r"\d+", rec.get("phases") or "") if int(x) in LIFECYCLE_PHASES]
        phases = st.multiselect("Lifecycle phases", list(LIFECYCLE_PHASES), default=cur_phases,
                                format_func=lambda p: f"{p}. {LIFECYCLE_PHASES[p]}")
        f1, f2, f3, f4 = st.columns(4)
        internet = f1.checkbox("Internet-facing", bool(rec.get("flag_internet")))
        sensitive = f2.checkbox("Handles sensitive data", bool(rec.get("flag_sensitive")))
        untrusted = f3.checkbox("Takes untrusted input", bool(rec.get("flag_untrusted")))
        third = f4.checkbox("Third party", bool(rec.get("flag_third_party")))
        notes = st.text_area("Notes", rec.get("notes") or "", height=120)
        saved = st.form_submit_button("Save system", type="primary")

    if saved:
        if not name.strip():
            st.error("Name is required.")
        else:
            sid = rec.get("system_id") or (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or new_id("sys"))
            if pick == "__new__" and sid in names:
                sid = f"{sid}-{new_id('x')[-4:]}"
            ui.store().upsert_systems([{
                "system_id": sid, "name": name.strip(), "component_type": ctype, "role": role,
                "vendor": vendor or None, "layers": ", ".join(layers),
                "phases": ", ".join(str(p) for p in sorted(phases)),
                "flag_internet": internet, "flag_sensitive": sensitive, "flag_untrusted": untrusted,
                "flag_third_party": third, "notes": notes or None, "source": rec.get("source") or "manual",
            }], ui.actor())
            ui.audit("system.save", "ai_systems", sid, name.strip())
            ui.refresh()
            st.session_state["current_system"] = sid
            st.success(f"Saved {name}.")
            st.rerun()

    if pick != "__new__":
        with st.expander("Delete this system"):
            st.warning("Deletes the system with all its findings and AI-CAIQ answers. The audit log keeps a record.")
            if st.checkbox(f"Yes, delete {names[pick]}", key=f"confirm-del-{pick}"):
                if st.button("Delete permanently", type="primary"):
                    ui.store().delete_system(pick)
                    ui.audit("system.delete", "ai_systems", pick, names[pick])
                    ui.refresh()
                    st.rerun()

# ---------------------------------------------------------------- findings
with tab_findings:
    system = ui.system_picker(key="findings-system")
    if system is not None:
        sid = system.system_id
        ctrl = ui.controls()[["control_id", "title"]]
        f = ui.findings(sid)
        if f.empty:
            st.caption("No findings yet.")
        else:
            f = f.merge(ctrl, on="control_id", how="left")
            edited = st.data_editor(
                f[["finding_id", "control_id", "title", "status", "note", "evidence", "updated_by"]],
                hide_index=True, width="stretch", key=f"findings-{sid}", disabled=["finding_id", "control_id", "title", "updated_by"],
                column_config={
                    "finding_id": None,
                    "status": st.column_config.SelectboxColumn("Status", options=FINDING_STATUSES, required=True),
                    "note": st.column_config.TextColumn("Observation", width="large"),
                    "evidence": st.column_config.TextColumn("Evidence"),
                },
            )
            changed = edited[(edited[["status", "note", "evidence"]].fillna("") != f[["status", "note", "evidence"]].fillna("")).any(axis=1)]
            if st.button(f"Save {len(changed)} change(s)", disabled=changed.empty, type="primary"):
                orig = f.set_index("finding_id")
                recs = []
                for r in changed.itertuples():
                    o = orig.loc[r.finding_id]
                    recs.append({"finding_id": r.finding_id, "system_id": sid, "control_id": r.control_id,
                                 "note": r.note, "evidence": r.evidence, "observed_at": o.observed_at,
                                 "source": o.source, "status": r.status})
                ui.store().upsert_findings(recs, ui.actor())
                ui.audit("finding.update", "findings", sid,
                         ", ".join(f"{r['control_id']}→{r['status']}" for r in recs))
                ui.refresh()
                st.rerun()

        with st.form(f"new-finding-{sid}", clear_on_submit=True):
            st.markdown("**Add a finding**")
            cids = ctrl.control_id.tolist()
            titles = dict(zip(ctrl.control_id, ctrl.title))
            cid = st.selectbox("Control", cids, format_func=lambda c: f"{c} – {titles[c]}")
            note = st.text_area("Observation *")
            ev = st.text_input("Evidence (file path, link, ticket)")
            status = st.selectbox("Status", FINDING_STATUSES)
            if st.form_submit_button("Add finding"):
                if not note.strip():
                    st.error("Observation is required.")
                else:
                    fid = new_id("F")
                    ui.store().upsert_findings([{
                        "finding_id": fid, "system_id": sid, "control_id": cid, "note": note.strip(),
                        "evidence": ev or None, "observed_at": pd.Timestamp.utcnow().to_pydatetime(),
                        "source": "Manual", "status": status}], ui.actor())
                    ui.audit("finding.create", "findings", fid, f"{sid} {cid}")
                    ui.refresh()
                    st.rerun()

# ---------------------------------------------------------------- import
with tab_import:
    st.markdown("Import an **aicm-mapper** workspace export (`.json`): components become AI systems and "
                "per-control scanner observations become findings. Re-importing the same file updates "
                "existing records rather than duplicating them.")
    up = st.file_uploader("Workspace export", type=["json"])
    if up is not None:
        try:
            data = json.loads(up.getvalue().decode("utf-8"))
            new_systems, new_findings = parse_workspace_export(data)
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")
        else:
            st.write(f"Found **{len(new_systems)}** components and **{len(new_findings)}** observations "
                     f"(source: `{(data.get('source') or {}).get('repo', 'unknown')}`).")
            st.dataframe(pd.DataFrame(new_systems)[["system_id", "name", "component_type", "role", "vendor"]],
                         hide_index=True, width="stretch")
            existing = set(ui.findings().finding_id) if not ui.findings().empty else set()
            if existing & {f["finding_id"] for f in new_findings}:
                st.caption("Findings already imported keep the status you set unless you choose otherwise below.")
            keep_status = st.checkbox("Keep current status of findings already imported", value=True)
            if st.button("Import", type="primary"):
                if keep_status and existing:
                    cur = ui.findings().set_index("finding_id").status.to_dict()
                    for f in new_findings:
                        f["status"] = cur.get(f["finding_id"], f["status"])
                ui.store().upsert_systems(new_systems, ui.actor())
                ui.store().upsert_findings(new_findings, ui.actor())
                ui.audit("inventory.import", "ai_systems", None,
                         f"{up.name}: {len(new_systems)} systems, {len(new_findings)} findings")
                ui.refresh()
                st.success("Imported.")
                st.rerun()
