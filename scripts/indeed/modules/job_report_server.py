#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Local FastAPI server for interactive HTML job reports + SQLite API."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.job_report_html import HTML_DIR, generate_reports

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"


def run_server(port=DEFAULT_PORT, regenerate=False, host=None):
    import uvicorn
    from modules.job_report_api import app, mount_static

    bind_host = host or os.environ.get("REPORT_HOST", DEFAULT_HOST)
    html_dir = HTML_DIR
    html_dir.mkdir(parents=True, exist_ok=True)
    if regenerate:
        generate_reports()
        print(f"Regenerated HTML in {html_dir}")
    else:
        print(f"Serving existing HTML from {html_dir} (pass regenerate=True to rebuild first)")

    mount_static(app)
    url = f"http://127.0.0.1:{port}/report_cards.html"
    print(f"Serving reports + API on http://{bind_host}:{port} (host browser: http://127.0.0.1:{port})")
    print(f"Interactive cards: {url}")
    print("Press Ctrl+C to stop")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Serve interactive job HTML reports")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=os.environ.get("REPORT_HOST", DEFAULT_HOST), help="Bind address (use 0.0.0.0 in Docker)",)
    parser.add_argument("--regenerate", action="store_true", help="Rebuild HTML before serving")
    
    args = parser.parse_args()
    run_server(port=args.port, regenerate=args.regenerate, host=args.host)
