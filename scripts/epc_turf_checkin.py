#!/usr/bin/env python3
"""
EPC Morning Turf Check-In — no_agent script.
Processes queued turf requests and delivers results to Travis via Telegram.
Runs daily Mon-Sat at 7am. Silent if no pending requests.
"""
import subprocess, json, os, sys

BOT      = json.load(open(os.path.expanduser("~/epc-webhook/config.json")))["TG_BOT_TOKEN"]
TRAVIS   = "6985623877"
TURF_DIR = "/Users/tdizzlewizzle/turf"

def send_tg(msg):
    payload = json.dumps({"chat_id": TRAVIS, "text": msg, "parse_mode": "Markdown",
                          "disable_web_page_preview": True})
    subprocess.run([
        "curl", "-s", "--max-time", "15", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        "-H", "Content-Type: application/json", "-d", payload
    ], capture_output=True)

# Check for pending requests
r = subprocess.run(["python3", "turf_queue.py", "list", "--status", "pending"],
                   capture_output=True, text=True, cwd=TURF_DIR)
if "No requests" in r.stdout or not r.stdout.strip():
    sys.exit(0)  # Silent — nothing queued

# Process the queue
r2 = subprocess.run(["python3", "turf_queue.py", "process"],
                    capture_output=True, text=True, cwd=TURF_DIR)

output = r2.stdout.strip()
if not output:
    sys.exit(0)

# Deliver each rep's result as a separate message (turf_queue.py outputs them separated)
# Split on double newlines or rep headers
messages = [m.strip() for m in output.split("\n\n\n") if m.strip()]
if not messages:
    messages = [output]

for msg in messages:
    if msg:
        send_tg(msg)
