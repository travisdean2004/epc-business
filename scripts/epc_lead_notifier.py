#!/usr/bin/env python3
"""
EPC Solar Lead Notifier — curl-based (Python SSL broken on this Mac).
Auto-discovers active form IDs from live ads every run.
Sends to HOT LEADS group + Travis DM.
"""
import json, os, sys, subprocess
from datetime import datetime, timezone, timedelta

with open(os.path.expanduser("~/epc-webhook/config.json")) as f:
    cfg = json.load(f)

TOKEN = cfg.get("SYSTEM_TOKEN") or cfg.get("PAGE_ACCESS_TOKEN", "")
BOT   = cfg["TG_BOT_TOKEN"]

SEND_TO      = ["-5476036884", "6985623877"]   # HOT LEADS + Travis DM
ADSET_ID     = "52556165350136"
SEEN_FILE    = os.path.expanduser("~/.hermes/epc_seen_leads.txt")
BACKUP_FORMS = [
    "2172031877076009",
    "1774376226890024",
    "1027659300246969",
    "2496854950754281",
    "2001630314050736",
]

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

def api(path):
    sep = "&" if "?" in path else "?"
    url = f"https://graph.facebook.com/v20.0/{path}{sep}access_token={TOKEN}"
    return curl_get(url)

def discover_forms():
    forms = set()
    ads = api(f"{ADSET_ID}/ads?fields=status,creative&limit=50")
    for ad in ads.get("data", []):
        if ad.get("status") not in ("ACTIVE", "PAUSED"):
            continue
        cid = ad.get("creative", {}).get("id")
        if not cid:
            continue
        spec = api(f"{cid}?fields=object_story_spec").get("object_story_spec", {})
        for key in ("video_data", "link_data", "photo_data"):
            fid = spec.get(key, {}).get("call_to_action", {}).get("value", {}).get("lead_gen_form_id")
            if fid:
                forms.add(fid)
    return list(forms) if forms else BACKUP_FORMS

# Load seen IDs
seen = set()
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE) as f:
        seen = set(l.strip() for l in f if l.strip())

form_ids  = discover_forms()
all_forms = list(dict.fromkeys(form_ids + BACKUP_FORMS))

new_leads_found = []
new_ids = []

HOT_BILLS = {
    "200_300", "300_400", "over_300", "over_400", "over_300_400",
    "$200-300", "$300-400", "Over $300", "Over $400", "200-300", "300-400"
}

for form_id in all_forms:
    data = api(f"{form_id}/leads?fields=id,created_time,field_data&limit=20")
    if "error" in data:
        continue
    for lead in data.get("data", []):
        if lead["id"] in seen:
            continue

        name = phone = email = bill = owner = home_type = timeline = dm = ""
        for fld in lead.get("field_data", []):
            n = fld["name"].lower()
            v = fld["values"][0] if fld.get("values") else ""
            if "full_name" in n or ("name" in n and "last" not in n and not name): name = v
            if "phone" in n:  phone = v
            if "email" in n:  email = v
            if "bill" in n or "electric" in n: bill = v
            if "own" in n and "home" in n:     owner = v
            if "type" in n and "home" in n:    home_type = v
            if "timeline" in n or ("when" in n and "look" in n): timeline = v
            if "decision" in n: dm = v

        dt = datetime.fromisoformat(lead["created_time"].replace("+0000", "+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        time_str = et.strftime("%b %d at %I:%M %p ET")

        owns   = owner.lower() not in ("no", "rent", "renter", "")
        is_hot = bill in HOT_BILLS and owns

        if is_hot:
            msg = f"🔥 EPC HOT LEAD — KIM CALL NOW\n👤 {name}\n📞 {phone}\n"
        else:
            msg = f"📋 EPC new lead\n👤 {name}\n📞 {phone}\n"
        if email:     msg += f"📧 {email}\n"
        if bill:      msg += f"💡 Bill: {bill}\n"
        if owner:     msg += f"🔑 Owns home: {owner}\n"
        if home_type: msg += f"🏠 Home: {home_type}\n"
        if dm:        msg += f"✅ Decision maker: {dm}\n"
        if timeline:  msg += f"📅 Timeline: {timeline}\n"
        msg += f"🕐 {time_str}\n"
        msg += "⚡ Call within 5 minutes!" if is_hot else "📲 Text follow-up."

        new_leads_found.append(msg)
        new_ids.append(lead["id"])

for msg in new_leads_found:
    for chat_id in SEND_TO:
        send_tg(chat_id, msg)

if new_ids:
    with open(SEEN_FILE, "a") as f:
        for lid in new_ids:
            f.write(lid + "\n")
# Silent exit on no new leads
