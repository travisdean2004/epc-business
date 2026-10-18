#!/usr/bin/env python3
"""
EPC Recruiting Text Sequence Engine — reply-driven, curl-based.
Flow:
  Text 1 (everyone, 90s after lead): intro + call or text?
  → They say "call"  → ping Kylan/Travis on Telegram to call them, stop texting
  → They say "text"  → Text 2 (qualify: sales exp + transport)
  → They reply Text 2 → Text 3 (income reality + hard worker?)
  → They reply positively to Text 3 → Text 4 (set up interview time)
  → They confirm interview → Telegram notification + Google Calendar link

Queue: ~/.hermes/recruit_text_queue.json
Seen replies: ~/.hermes/recruit_seen_replies.txt
"""
import json, os, sys, subprocess, time, re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

CFG_PATH     = os.path.expanduser("~/epc-webhook/config.json")
QUEUE_FILE   = os.path.expanduser("~/.hermes/recruit_text_queue.json")
SEEN_REPLIES = os.path.expanduser("~/.hermes/recruit_seen_replies.txt")

cfg          = json.load(open(CFG_PATH))
TWILIO_SID   = cfg["TWILIO_SID"]
TWILIO_TOKEN = cfg["TWILIO_TOKEN"]
TWILIO_FROM  = cfg["TWILIO_FROM"]
MESSAGING_SVC = "MG90e48e9e5a7a4c0a1c865d627fce762c"
BOT          = cfg["TG_BOT_TOKEN"]
TRAVIS       = "6985623877"
OFFICE_ADDR  = "331 Scarlet Blvd, Oldsmar FL 34677"

NOW = time.time()

INTERVIEW_MAP = {
    "thursday":  "Thursday",
    "wednesday": "Wednesday",
    "tuesday":   "Tuesday",
    "monday":    "Monday",
    "friday":    "Friday",
    "saturday":  "Saturday",
    "thu_12":    "Thursday at 12pm",
    "wed_12":    "Wednesday at 12pm",
    "tue_12":    "Tuesday at 12pm",
    "mon_12":    "Monday at 12pm",
}

# ── Texts ─────────────────────────────────────────────────────────────────────
def text1(name):
    first = name.split()[0] if name else "there"
    return (
        f"Hey {first}, it's Kylan, In House Manager at EPC Contractors. "
        f"Saw you just filled out our form for the Career Position - appreciate you reaching out. "
        f"Got a couple quick questions to make sure this is the right fit for you. "
        f"Are you free for a quick call or would text work better for you right now?"
    )

def text2():
    return (
        "Okay no worries. Do you have any sales experience? "
        "And do you have reliable transportation to get to our office? "
        "Just want to be upfront before we go any further"
    )

def text3(name):
    first = name.split()[0] if name else "there"
    return (
        f"Also want to be straight with you {first} - this is 3-4 days a week out in the field. "
        f"Our reps working those days are making $150,000-$250,000 their first year. "
        f"Not easy money but it is real money. You a hard worker?"
    )

def text4(interview_day):
    day = INTERVIEW_MAP.get((interview_day or "").lower(), interview_day or "the day you selected")
    return (
        f"Love to hear it. You picked {day} on your form - does that still work for you "
        f"to come check us out at the office? Let me know and I will get you set up"
    )

def text_confirmed(name, interview_day):
    first = name.split()[0] if name else "there"
    day   = INTERVIEW_MAP.get((interview_day or "").lower(), interview_day or "the day you selected")
    return (
        f"Perfect {first}, you are locked in for {day}. "
        f"Come to {OFFICE_ADDR}. "
        f"See you then - looking forward to it"
    )

# ── Reply intent detection ─────────────────────────────────────────────────────
def wants_call(text):
    t = text.lower()
    return any(w in t for w in ["call", "phone", "talk", "ring", "number"])

def wants_text(text):
    t = text.lower()
    return any(w in t for w in ["text", "message", "msg", "prefer text", "text works", "text is fine", "text me"])

def is_positive(text):
    t = text.lower()
    neg = any(w in t for w in ["no ", "nah", "not interested", "never mind", "nevermind", "pass", "can't", "cannot", "nope"])
    pos = any(w in t for w in [
        "yes", "yeah", "yep", "yup", "sure", "absolutely", "of course", "definitely",
        "hard worker", "i am", "lets go", "let's go", "im in", "i'm in", "sounds good",
        "interested", "ready", "let's do", "lets do", "for sure", "100", "i work hard",
        "count me", "sign me", "i do", "i can", "i will"
    ])
    return pos and not neg

def confirmed_interview(text):
    t = text.lower()
    return any(w in t for w in [
        "yes", "yeah", "yep", "works", "good", "perfect", "sure", "absolutely",
        "i'll be there", "ill be there", "see you", "confirmed", "ok", "okay",
        "sounds good", "let's do", "lets do", "i'm in", "im in", "that works"
    ])

# ── Google Calendar one-tap link ───────────────────────────────────────────────
def gcal_link(name, interview_day):
    first = name.split()[0] if name else "Recruit"
    day_label = INTERVIEW_MAP.get((interview_day or "").lower(), "Thursday")

    # Build a date — find next occurrence of that day
    today = datetime.now()
    day_map = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
        "Friday": 4, "Saturday": 5, "Sunday": 6
    }
    # Extract base day name
    base_day = day_label.split(" at ")[0]
    hour = 12 if "12pm" in day_label else 10  # default 10am unless 12pm specified

    target_wd = day_map.get(base_day, 3)
    days_ahead = (target_wd - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # push to next week if today
    interview_date = today + timedelta(days=days_ahead)
    start = interview_date.replace(hour=hour, minute=0, second=0, microsecond=0)
    end   = start + timedelta(hours=1)

    fmt = "%Y%m%dT%H%M%S"
    title = quote(f"EPC Interview - {first}")
    loc   = quote(OFFICE_ADDR)
    dates = f"{start.strftime(fmt)}/{end.strftime(fmt)}"

    return f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={title}&dates={dates}&location={loc}"

# ── Helpers ───────────────────────────────────────────────────────────────────
def send_sms(to, body):
    r = subprocess.run([
        "curl", "-s", "--max-time", "15", "-X", "POST",
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
        "-u", f"{TWILIO_SID}:{TWILIO_TOKEN}",
        "--data-urlencode", f"To={to}",
        "--data-urlencode", f"MessagingServiceSid={MESSAGING_SVC}",
        "--data-urlencode", f"Body={body}",
    ], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout) if r.stdout.strip() else {}
        return d.get("sid"), d.get("error_message") or d.get("message")
    except:
        return None, r.stdout[:120]

def send_tg(chat_id, text):
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False})
    subprocess.run([
        "curl", "-s", "--max-time", "10", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        "-H", "Content-Type: application/json", "-d", payload
    ], capture_output=True, text=True)

def normalize_phone(p):
    return "".join(c for c in p if c.isdigit())[-10:]

# ── Load queue ────────────────────────────────────────────────────────────────
queue = {}
if os.path.exists(QUEUE_FILE):
    try:
        queue = json.load(open(QUEUE_FILE))
    except:
        queue = {}

# ── Load seen reply SIDs ──────────────────────────────────────────────────────
seen_sids = set()
if os.path.exists(SEEN_REPLIES):
    with open(SEEN_REPLIES) as f:
        seen_sids = set(l.strip() for l in f if l.strip())

# ── Fetch inbound replies from Twilio ─────────────────────────────────────────
r = subprocess.run([
    "curl", "-s", "--max-time", "15",
    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    f"?Direction=inbound&PageSize=50",
    "-u", f"{TWILIO_SID}:{TWILIO_TOKEN}"
], capture_output=True, text=True)
inbound_data = json.loads(r.stdout) if r.stdout.strip() else {}
inbound_msgs = inbound_data.get("messages", [])

# Map phone → lead for reply matching
phone_to_lead_id = {
    normalize_phone(l["phone"]): lid
    for lid, l in queue.items()
    if l.get("phone")
}

new_sids = []
changed  = False

# ── Process inbound replies ───────────────────────────────────────────────────
for msg in reversed(inbound_msgs):  # oldest first
    sid  = msg.get("sid", "")
    if sid in seen_sids:
        continue

    body = (msg.get("body") or "").strip()
    frm  = msg.get("from", "")
    new_sids.append(sid)

    lead_id = phone_to_lead_id.get(normalize_phone(frm))
    if not lead_id or lead_id not in queue:
        continue

    lead = queue[lead_id]
    if lead.get("done") or lead.get("opted_out"):
        continue

    stage     = lead.get("stage", 0)
    name      = lead.get("name", "there")
    phone     = lead.get("phone", "")
    interview = lead.get("interview_day", "")

    print(f"Reply from {name} (stage {stage}): {body[:60]}")

    # Stage 1: waiting for call vs text response
    if stage == 1:
        if wants_call(body):
            # Ping Travis/Kylan to call them
            send_tg(TRAVIS,
                f"RECRUIT WANTS A CALL\n"
                f"Name: {name}\n"
                f"Phone: {phone}\n"
                f"Reply: \"{body}\"\n\n"
                f"Call them now - they are ready to talk"
            )
            lead["stage"]   = 99  # human takeover
            lead["done"]    = True
            changed = True
            print(f"  -> Wants call, pinged Travis")
        elif wants_text(body) or len(body) > 2:
            # Send Text 2
            sid2, err = send_sms(phone, text2())
            if sid2:
                lead["stage"] = 2
                changed = True
                print(f"  -> Sent Text 2 to {name}")
            else:
                print(f"  -> Text 2 FAILED: {err}")

    # Stage 2: waiting for sales exp + transport answer
    elif stage == 2:
        sid3, err = send_sms(phone, text3(name))
        if sid3:
            lead["stage"] = 3
            changed = True
            print(f"  -> Sent Text 3 to {name}")
        else:
            print(f"  -> Text 3 FAILED: {err}")

    # Stage 3: waiting for hard worker response
    elif stage == 3:
        if is_positive(body):
            sid4, err = send_sms(phone, text4(interview))
            if sid4:
                lead["stage"] = 4
                changed = True
                print(f"  -> Sent Text 4 to {name}")
            else:
                print(f"  -> Text 4 FAILED: {err}")
        else:
            # Not interested — graceful exit, mark done
            lead["done"]     = True
            lead["opted_out"] = True
            changed = True
            print(f"  -> {name} not interested, stopping sequence")

    # Stage 4: waiting for interview confirmation
    elif stage == 4:
        if confirmed_interview(body):
            # Send confirmation text to recruit
            send_sms(phone, text_confirmed(name, interview))

            # Build Google Calendar link
            cal_link = gcal_link(name, interview)
            day_label = INTERVIEW_MAP.get((interview or "").lower(), interview or "TBD")

            # Notify Travis on Telegram
            send_tg(TRAVIS,
                f"INTERVIEW CONFIRMED\n\n"
                f"Name: {name}\n"
                f"Phone: {phone}\n"
                f"Day: {day_label}\n"
                f"Location: {OFFICE_ADDR}\n\n"
                f"Add to calendar:\n{cal_link}"
            )

            lead["stage"]    = 5
            lead["done"]     = True
            lead["confirmed"] = True
            changed = True
            print(f"  -> INTERVIEW CONFIRMED: {name} on {day_label}")
        else:
            # They said no or different day — ping Travis to handle manually
            send_tg(TRAVIS,
                f"RECRUIT RESCHEDULING\n\n"
                f"Name: {name}\n"
                f"Phone: {phone}\n"
                f"Reply: \"{body}\"\n\n"
                f"They may want a different day - handle manually"
            )
            lead["done"] = True
            changed = True
            print(f"  -> {name} needs manual follow-up")

# ── Fire Text 1 for newly queued leads (90s timer) ───────────────────────────
for lead_id, lead in queue.items():
    if lead.get("done") or lead.get("opted_out"):
        continue
    if lead.get("stage", 0) != 0:
        continue

    queued_at = lead.get("queued_at", NOW)
    if NOW - queued_at < 90:
        continue  # not time yet

    name  = lead.get("name", "")
    phone = lead.get("phone", "")
    if not phone:
        lead["done"] = True
        changed = True
        continue

    sid1, err = send_sms(phone, text1(name))
    if sid1:
        lead["stage"] = 1
        lead["text1_sent_at"] = NOW
        changed = True
        print(f"Sent Text 1 to {name} ({phone})")
    else:
        print(f"Text 1 FAILED for {name}: {err}")

# ── Save seen reply SIDs ──────────────────────────────────────────────────────
if new_sids:
    with open(SEEN_REPLIES, "a") as f:
        for s in new_sids:
            f.write(s + "\n")

# ── Save queue ────────────────────────────────────────────────────────────────
if changed:
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)
