#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Import JSON artifacts into SQLite and generate HTML report variants."""

import os
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.job_report_html import VARIANTS, generate_reports, HTML_DIR
from modules.job_store import default_db_path, import_all_json


def main():
    parser = argparse.ArgumentParser(description="Import scrape JSON into SQLite and build HTML reports")
    parser.add_argument("--import-json", action="store_true", help="Import all artifacts/json/*.json into jobs.db (skips combined_*)",)
    parser.add_argument("--variants", type=str, default="index,dashboard,table,search,companies,cards,screenshots,compare", help=f"Comma-separated report types: {','.join(VARIANTS)}",)
    parser.add_argument("--json-dir", type=str, default=None, help="JSON artifacts directory")
    parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    parser.add_argument("--out", type=str, default=None, help="HTML output directory")
    parser.add_argument("--serve", action="store_true", help="Start interactive server (does not rebuild HTML unless --regenerate or --import-json)",)
    parser.add_argument("--regenerate", action="store_true", help="With --serve, rebuild HTML before starting server")
    parser.add_argument("--prototypes", action="store_true", help="Also generate 3 themed UI prototypes under artifacts/html/prototypes/",)
    parser.add_argument("--port", type=int, default=8765, help="Port for --serve")
    parser.add_argument("--host", default=os.environ.get("REPORT_HOST", "127.0.0.1"), help="Bind address for --serve (use 0.0.0.0 in Docker)",)
    args = parser.parse_args()

    db_path = args.db or str(default_db_path())
    out_dir = args.out or str(HTML_DIR)

    if args.import_json:
        totals = import_all_json(json_dir=args.json_dir, db_path=db_path)
        print(
            f"Imported {totals['files']} JSON files "
            f"({totals.get('skipped', 0)} already in DB) → "
            f"{totals['new']} new jobs, {totals['updated']} updated, "
            f"{totals['sightings']} sightings"
        )

    should_generate = not args.serve or args.regenerate or args.import_json
    written = {}
    if should_generate:
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]
        written = generate_reports(
            variants=variants,
            json_dir=args.json_dir,
            db_path=db_path,
            output_dir=out_dir,
        )

        print(f"\nHTML reports written to: {out_dir}")
        for name, path in written.items():
            print(f"  [{name}] file://{path}")

        if "index" in written:
            print(f"\nStatic files: file://{written['index']}")
            print("Interactive (Apply/Skip, Jobs/Search API): python3 modules/generate_job_reports.py --serve")

    if args.prototypes:
        from modules.job_report_prototypes import generate_prototypes

        proto_written = generate_prototypes(
            json_dir=args.json_dir,
            db_path=db_path,
        )
        print("\nUI prototypes written to: artifacts/html/prototypes/")
        for name, path in proto_written.items():
            print(f"  [{name}] file://{path}")

    if args.serve:
        from modules.job_report_server import run_server

        run_server(port=args.port, regenerate=False, host=args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
