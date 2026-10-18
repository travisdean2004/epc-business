#!/usr/bin/env python3
"""
EPC Interview Confirmation Reminders — no_agent script.
Runs Tue + Thu at 9am. Texts confirmed interviewees, notifies Travis.
"""
import json, os, subprocess, sys

CFG_PATH   = os.path.expanduser("~/epc-webhook/config.json")
QUEUE_FILE = os.path.expanduser("~/.hermes/recruit_text_queue.json")
TRAVIS_ID  = "6985623877"

cfg          = json.load(open(CFG_PATH))
TWILIO_SID   = cfg["TWILIO_SID"]
TWILIO_TOKEN = cfg["TWILIO_TOKEN"]
TWILIO_FROM  = cfg["TWILIO_FROM"]
BOT          = cfg["TG_BOT_TOKEN"]

queue = {}
if os.path.exists(QUEUE_FILE):
    try:
        queue = json.load(open(QUEUE_FILE))
    except:
        pass

confirmed = [r for r in queue.values() if isinstance(r, dict) and
             (r.get("stage") == 4 or r.get("confirmed")) and not r.get("done")]

if not confirmed:
    sys.exit(0)  # Silent — no one confirmed today

def send_sms(to, body):
    r = subprocess.run([
        "curl", "-s", "--max-time", "15", "-X", "POST",
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
        "--user", f"{TWILIO_SID}:{TWILIO_TOKEN}",
        "--data-urlencode", f"From={TWILIO_FROM}",
        "--data-urlencode", f"To={to}",
        "--data-urlencode", f"Body={body}",
    ], capture_output=True, text=True)
    result = json.loads(r.stdout) if r.stdout.strip() else {}
    return result.get("sid")

def send_tg(chat_id, msg):
    payload = json.dumps({"chat_id": chat_id, "text": msg})
    subprocess.run([
        "curl", "-s", "--max-time", "10", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        "-H", "Content-Type: application/json", "-d", payload
    ], capture_output=True)

sent = []
failed = []
for r in confirmed:
    name  = r.get("name", "")
    phone = r.get("phone", "")
    first = name.split()[0] if name else "there"
    if not phone:
        continue
    msg = (f"Hey {first} — just a quick reminder your interview with EPC Contractors "
           f"is TODAY at 10am. 331 Scarlet Blvd, Oldsmar FL 34677. See you soon!")
    sid = send_sms(phone, msg)
    if sid:
        sent.append(f"{name} ({phone})")
    else:
        failed.append(f"{name} ({phone})")

# Notify Travis
summary = f"📅 Interview reminders sent — {len(sent)} confirmed for today's 10am:\n"
summary += "\n".join(f"  • {s}" for s in sent)
if failed:
    summary += f"\n\n⚠️ Failed to text: {', '.join(failed)}"
send_tg(TRAVIS_ID, summary)
