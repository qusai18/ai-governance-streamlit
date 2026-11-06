"""Load data into the AI governance Lakebase schema from your laptop.

Deploy the Databricks App first: on startup it creates the `aigov` schema (so the app's
service principal owns it) and seeds the AICM + AI-CAIQ reference data. Then use this to
import an inventory export or reload the reference data as yourself.

Usage (from the project folder):
    python scripts/setup_databricks.py --profile DEFAULT \
        --endpoint projects/ai-governance/branches/production/endpoints/primary \
        [--import-inventory data/<export>.json] [--reload-reference] [--create-schema]
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.aicm_parse import parse_aicm, parse_caiq  # noqa: E402
from lib.connection import Settings, make_pool  # noqa: E402
from lib.inventory import parse_workspace_export  # noqa: E402
from lib.store import Store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="DEFAULT")
    ap.add_argument("--endpoint", default="projects/ai-governance/branches/production/endpoints/primary")
    ap.add_argument("--database", default="databricks_postgres")
    ap.add_argument("--schema", default="aigov")
    ap.add_argument("--create-schema", action="store_true",
                    help="create tables as YOU (only for a schema the app will not own)")
    ap.add_argument("--reload-reference", action="store_true", help="reload AICM/AI-CAIQ from data/")
    ap.add_argument("--import-inventory", help="aicm-mapper workspace JSON to import")
    args = ap.parse_args()

    settings = Settings(endpoint=args.endpoint, pg_host="", pg_database=args.database,
                        schema=args.schema, profile=args.profile)
    ws = settings.workspace_client()
    settings.pg_host = ws.postgres.get_endpoint(name=args.endpoint).status.hosts.host
    actor = f"setup-script:{getpass.getuser()}"
    t0 = time.time()
    pool = make_pool(settings, min_size=1, max_size=2)
    try:
        store = Store(pool, args.schema)
        print(f"Connected to {settings.pg_host} as {pool.pg_user}")
        if args.create_schema:
            store.ensure_schema()
        exists = store.query("SELECT to_regclass(%(t)s) AS t", {"t": f"{args.schema}.ai_systems"}).t[0]
        if not exists:
            sys.exit(f"Schema {args.schema} has no tables yet. Deploy the app first (it creates them), "
                     "or pass --create-schema.")

        if args.reload_reference:
            controls = parse_aicm(str(ROOT / "data" / "AICMv1.1.1.xlsx"))
            questions = parse_caiq(str(ROOT / "data" / "AI-CAIQv1.1.0_template.xlsx"))
            store.load_reference_data(controls, questions)
            store.audit(actor, "cli-profile", "reference.load", "aicm_controls", None,
                        f"{len(controls)} controls, {len(questions)} questions")
            print(f"Loaded {len(controls)} controls and {len(questions)} questions")

        if args.import_inventory:
            data = json.loads(Path(args.import_inventory).read_text(encoding="utf-8"))
            systems, findings = parse_workspace_export(data)
            store.upsert_systems(systems, actor)
            store.upsert_findings(findings, actor)
            store.audit(actor, "cli-profile", "inventory.import", "ai_systems", None,
                        f"{Path(args.import_inventory).name}: {len(systems)} systems, {len(findings)} findings")
            print(f"Imported {len(systems)} systems and {len(findings)} findings")

        counts = store.query(" UNION ALL ".join(
            f"SELECT '{t}' AS table_name, count(*) AS row_count FROM {store.s}.{t}"
            for t in ("aicm_controls", "caiq_questions", "ai_systems", "findings", "caiq_answers", "audit_log")))
        print(counts.to_string(index=False))
    finally:
        pool.close()
    print(f"Done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
