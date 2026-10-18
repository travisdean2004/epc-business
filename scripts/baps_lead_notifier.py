#!/usr/bin/env python3
"""
BAPS Lead Notifier — curl-based (Python SSL broken on this Mac).
Pulls new leads from all BAPS forms, posts ONE grouped message to BAPS HOT LEADS chat.
"""
import json, os, sys, subprocess
from datetime import datetime, timezone, timedelta

CFG_PATH  = os.path.expanduser("~/epc-webhook/config.json")
SEEN_FILE = os.path.expanduser("~/.hermes/baps_seen_leads.txt")

try:
    with open(CFG_PATH) as f:
        cfg = json.load(f)
except Exception as e:
    print(f"FATAL: cannot read config: {e}")
    sys.exit(1)

TOKEN = cfg.get("BAPS_PAGE_TOKEN") or cfg.get("BAPS_TOKEN") or cfg.get("PAGE_ACCESS_TOKEN") or cfg.get("SYSTEM_TOKEN", "")
BOT       = cfg.get("TG_BOT_TOKEN", "")
BAPS_CHAT = "-5523363296"   # BAPS WRAPS HOT LEADS only

FORMS = [
    "976671118677598",
    "2335238027215365",
    "814374288308368",
    "1629612594768748",
    "998586169797328",
    "924973566194769",
]

ET = timezone(timedelta(hours=-4))

def curl_get(url):
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "15", url],
                           capture_output=True, text=True)
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {}

def send_tg(chat_id, text):
    payload = json.dumps({"chat_id": chat_id, "text": text})
    try:
        r = subprocess.run([
            "curl", "-s", "--max-time", "10", "-X", "POST",
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            "-H", "Content-Type: application/json",
            "-d", payload
        ], capture_output=True, text=True)
        result = json.loads(r.stdout) if r.stdout.strip() else {}
        return result.get("ok", False)
    except Exception:
        return False

# Load seen IDs
seen = set()
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE) as f:
        seen = set(l.strip() for l in f if l.strip())

new_leads = []
new_ids   = []

for form_id in FORMS:
    url = f"https://graph.facebook.com/v20.0/{form_id}/leads?fields=id,created_time,field_data&limit=25&access_token={TOKEN}"
    data = curl_get(url)
    if "error" in data:
        continue  # silent — bad form IDs happen, don't crash
    for lead in data.get("data", []):
        lid = lead["id"]
        if lid in seen:
            continue

        fields = {}
        for fld in lead.get("field_data", []):
            key = fld["name"].lower().strip()
            val = fld.get("values", [""])[0]
            fields[key] = val

        name      = fields.get("full_name") or fields.get("name", "Unknown")
        phone     = fields.get("phone_number") or fields.get("phone", "")
        email     = fields.get("email", "")
        vehicle   = fields.get("vehicle_type", "")
        wrap_type = fields.get("wrap_type", "")
        timeline  = fields.get("timeline", "")

        dt = datetime.fromisoformat(lead["created_time"].replace("+0000", "+00:00"))
        et_time = dt.astimezone(ET)
        time_str = et_time.strftime("%b %d at %I:%M %p ET")

        entry  = f"Name: {name}\n"
        entry += f"Phone: {phone}\n"
        if email:     entry += f"Email: {email}\n"
        if vehicle:   entry += f"Vehicle: {vehicle}\n"
        if wrap_type: entry += f"Wrap: {wrap_type}\n"
        if timeline:  entry += f"Timeline: {timeline}\n"
        entry += f"Time: {time_str}"

        new_leads.append(entry)
        new_ids.append(lid)
        seen.add(lid)

if new_leads:
    if len(new_leads) == 1:
        msg = f"🚗 NEW BAPS WRAP LEAD\n\n{new_leads[0]}\n\nCall them NOW!"
    else:
        body = "\n\n".join(f"#{i+1}\n{lead}" for i, lead in enumerate(new_leads))
        msg = f"🚗 {len(new_leads)} NEW BAPS WRAP LEADS\n\n{body}\n\nCall them NOW!"

    send_tg(BAPS_CHAT, msg)
    with open(SEEN_FILE, "a") as f:
        for lid in new_ids:
            f.write(lid + "\n")
# Silent exit on no new leads
