#!/usr/bin/env python3
"""
EPC Recruiting Lead Notifier — uses curl for all HTTPS (Python SSL broken on this Mac).
Checks every form in the recruiting adset, fires to EPC NEW HIRES chat.
"""
import json, os, subprocess, time
from datetime import datetime, timezone, timedelta

QUEUE_FILE = os.path.expanduser("~/.hermes/recruit_text_queue.json")

def enqueue_lead(lead_id, name, phone, interview_day):
    """Add a new lead to the text sequence queue."""
    queue = {}
    if os.path.exists(QUEUE_FILE):
        try:
            queue = json.load(open(QUEUE_FILE))
        except:
            queue = {}
    if lead_id not in queue:
        queue[lead_id] = {
            "name": name,
            "phone": phone,
            "interview_day": interview_day,
            "queued_at": time.time(),
            "stage": 0,
            "stage_times": [None, None, None, None],
            "done": False,
        }
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2)

with open(os.path.expanduser("~/epc-webhook/config.json")) as f:
    cfg = json.load(f)

TOKEN = cfg.get("PAGE_ACCESS_TOKEN") or cfg.get("SYSTEM_TOKEN", "")
BOT   = cfg["TG_BOT_TOKEN"]

SEND_TO        = ["-5306696575"]   # EPC NEW HIRES
RECRUIT_ADSETS = ["52562860645536", "52576939649536"]  # old + new instant form adset
SEEN_FILE      = os.path.expanduser("~/.hermes/epc_recruiting_seen_leads.txt")
BACKUP_FORMS   = [
    "28723214310651463",  # Oct 2026 recruiting reel ad form
    "2235441740353078",   # v2 — FT/PT + start date (active)
    "1036750986029192",   # v1 — simple form
    "1763068848451143",   # original recruiting form
    "1335806338623894",   # old fallback
]

def curl_get(url):
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "15", url],
                           capture_output=True, text=True)
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {}

def api(path):
    sep = "&" if "?" in path else "?"
    url = f"https://graph.facebook.com/v20.0/{path}{sep}access_token={TOKEN}"
    return curl_get(url)

def send_tg(chat_id, text):
    payload = json.dumps({"chat_id": chat_id, "text": text})
    try:
        r = subprocess.run([
            "curl", "-s", "--max-time", "10",
            "-X", "POST",
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            "-H", "Content-Type: application/json",
            "-d", payload
        ], capture_output=True, text=True)
        result = json.loads(r.stdout) if r.stdout.strip() else {}
        return result.get("ok", False)
    except Exception:
        return False

def discover_forms():
    forms = set()
    for RECRUIT_ADSET in RECRUIT_ADSETS:
      ads = api(f"{RECRUIT_ADSET}/ads?fields=status,creative&limit=50")
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

new_msgs = []
new_ids  = []

CUTOFF = datetime(2026, 9, 14, 0, 0, 0, tzinfo=timezone.utc)

for form_id in all_forms:
    data = api(f"{form_id}/leads?fields=id,created_time,field_data&limit=20")
    for lead in data.get("data", []):
        if lead["id"] in seen:
            continue
        lead_dt = datetime.fromisoformat(lead["created_time"].replace("+0000", "+00:00"))
        if lead_dt < CUTOFF:
            continue

        name = phone = email = experience = transport = interview = employment_type = start_timeline = ""
        for fld in lead.get("field_data", []):
            n = fld["name"].lower()
            v = fld["values"][0] if fld.get("values") else ""
            if "full_name" in n or ("name" in n and not name): name = v
            if "phone" in n:           phone = v
            if "email" in n:           email = v
            if "experience" in n or "sales" in n: experience = v
            if "transport" in n:       transport = v
            if "interview" in n:       interview = v
            if "employment_type" in n: employment_type = v
            if "start_timeline" in n:  start_timeline = v

        dt = datetime.fromisoformat(lead["created_time"].replace("+0000", "+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        time_str = et.strftime("%b %d at %I:%M %p ET")

        transport_icon = "✅" if transport.lower() == "yes" else ("⚠️ NO CAR" if transport == "no" else "")
        exp_label = {"d2d": "D2D ✅", "other_sales": "Other Sales", "no_exp": "No Exp"}.get(experience, experience)

        msg = f"🧑‍💼 NEW REP APPLICANT — [FACEBOOK]\n"
        msg += f"👤 {name}\n"
        msg += f"📞 {phone}\n"
        if email:            msg += f"📧 {email}\n"
        if exp_label:        msg += f"💼 {exp_label}\n"
        if transport:        msg += f"🚗 Transport: {transport_icon}\n"
        if employment_type:  msg += f"⏰ {employment_type}\n"
        if start_timeline:   msg += f"🚀 Start: {start_timeline}\n"
        if interview:        msg += f"📅 Interview: {interview}\n"
        msg += f"🕐 {time_str}\n"
        msg += f"📲 Call within 5 minutes!"

        new_msgs.append(msg)
        new_ids.append(lead["id"])

        # Enqueue for automated text sequence (fires ~90s after lead comes in)
        if phone:
            enqueue_lead(lead["id"], name, phone, interview)

for msg in new_msgs:
    for chat_id in SEND_TO:
        send_tg(chat_id, msg)

if new_ids:
    with open(SEEN_FILE, "a") as f:
        for lid in new_ids:
            f.write(lid + "\n")
    print(f"Delivered {len(new_ids)} recruiting lead(s) to NEW HIRES chat")
    # Run texter immediately — only fires when there are actually new leads
    import subprocess as _sp
    _sp.run(["python3", os.path.expanduser("~/.hermes/scripts/epc_recruit_texter.py")],
            capture_output=True, timeout=30)
    print("Text sequence triggered for new leads")
    pass  # Silent exit — no output = no delivery
