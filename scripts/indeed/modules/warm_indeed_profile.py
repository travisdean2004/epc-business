#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Warm Indeed Chrome profile — pass Cloudflare once in REAL Chrome (not Selenium).

Cloudflare detects Selenium-controlled browsers and loops Turnstile forever.
Use this script to open normal Chrome with remote debugging enabled, pass
Cloudflare manually, then keep Chrome open while the scraper attaches.

Usage:
    python modules/warm_indeed_profile.py

Then in another terminal (Chrome still open):
    python src/main.py
"""

import sys
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.sb_utils import (DEFAULT_INDEED_DEBUG_PORT, board_debug_port, board_profile_dir, is_chrome_debug_port_open, warm_inject_saved_cookies, wait_for_chrome_debug_port,)

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LINUX_CHROME_CANDIDATES = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)
INDEED_JOBS = "https://www.indeed.com/jobs"
BOARD_WARMUP_URLS = {
    "indeed": INDEED_JOBS,
    "dice": "https://www.dice.com/jobs",
    "glassdoor": "https://www.glassdoor.com/Job/jobs.htm",
}


def warmup_url_for_board(board):
    return BOARD_WARMUP_URLS.get((board or "indeed").lower(), INDEED_JOBS)


def find_chrome_binary():
    if Path(MAC_CHROME).exists():
        return MAC_CHROME
    for candidate in LINUX_CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description="Open real Chrome for job board Cloudflare warmup")
    parser.add_argument("--board", choices=("indeed", "dice", "glassdoor"), default="indeed", help="Job board to warm up (default: indeed)",)
    parser.add_argument("--debug-port", type=int, default=None, help="Remote debugging port (default: per board — Indeed 9222, Glassdoor 9223, Dice 9224)",)
    parser.add_argument("--detach", action="store_true", help="Launch Chrome in background and exit once debug port is ready (for orchestrator scripts)",)
    parser.add_argument("--skip-cookie-inject", action="store_true", help="Do not load indeed_cookies.pkl into the Chrome profile at startup",)
    args = parser.parse_args()

    profile = board_profile_dir(args.board)
    profile.mkdir(parents=True, exist_ok=True)
    debug_port = args.debug_port if args.debug_port is not None else board_debug_port(args.board)
    warmup_url = warmup_url_for_board(args.board)
    board_label = args.board.title()

    print("\n" + "=" * 70)
    print(f"{board_label.upper()} PROFILE WARMUP (real Chrome — not Selenium)")
    print("=" * 70)
    print(f"Board:       {args.board}")
    print(f"Profile:     {profile}")
    print(f"Debug port:  {debug_port}")
    print(f"Start URL:   {warmup_url}")
    print("\nSteps:")
    print("  1. Chrome opens with the scraper profile + remote debugging")
    if args.board == "indeed":
        print("  2. Saved indeed_cookies.pkl is injected into the profile when present")
    print("  3. Pass Cloudflare in this window if prompted (click verify once)")
    print(f"  4. Confirm you see {board_label} job listings")
    print("  5. KEEP CHROME OPEN — do not quit (Cmd+Q)")
    print("\nThen in another terminal:")
    print(f"  python src/main.py --auto --board {args.board} --query \"...\" --max 25")
    print("\nThe scraper auto-attaches when this Chrome is still running.")
    print("Optional: INDEED_ATTACH=1 python src/main.py")
    print("=" * 70 + "\n")

    chrome_bin = find_chrome_binary()
    if not chrome_bin:
        print("Chrome not found. Install Google Chrome or open manually with:")
        print(f"  --user-data-dir={profile}")
        print(f"  --remote-debugging-port={debug_port}")
        print(f"  {warmup_url}")
        return 1

    chrome_args = [
        chrome_bin,
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={debug_port}",
        warmup_url,
    ]

    def maybe_inject_cookies():
        if args.skip_cookie_inject or args.board != "indeed":
            if args.board != "indeed":
                print(f"No cookie pickle inject for {args.board} — pass Cloudflare once in this window")
            else:
                print("Skipping cookie inject (--skip-cookie-inject)")
            return
        warm_inject_saved_cookies(port=debug_port, jobs_url=warmup_url)

    if args.detach:
        if is_chrome_debug_port_open(debug_port):
            print(f"Debug port {debug_port} already open — reusing existing Chrome")
            maybe_inject_cookies()
            return 0
        proc = subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,)
        print(f"CHROME_PID={proc.pid}")
        try:
            wait_for_chrome_debug_port(debug_port, timeout=90)
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            proc.terminate()
            return 1
        maybe_inject_cookies()
        print(f"Chrome ready on debug port {debug_port} (PID {proc.pid})")
        print("Pass Cloudflare in that window if needed, then run the scraper.")
        return 0

    proc = subprocess.Popen(chrome_args)
    try:
        wait_for_chrome_debug_port(debug_port, timeout=90)
        maybe_inject_cookies()
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        proc.terminate()
        return 1

    print("\nChrome closed. Re-run this script before scraping if Cloudflare blocks again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
