#!/usr/bin/env python3
"""
EPC Recruiting Pipeline Report — fires every Monday 7am
Reads the recruit text queue and sends Travis a weekly summary:
- Total applicants in pipeline
- Breakdown by stage
- Confirmed interviews
- Stale leads (3+ days, no reply)
- Action items
"""
import json, os, time, subprocess
from datetime import datetime, timezone, timedelta

QUEUE_FILE   = os.path.expanduser("~/.hermes/recruit_text_queue.json")
CFG_PATH     = os.path.expanduser("~/epc-webhook/config.json")

cfg = json.load(open(CFG_PATH))
BOT    = cfg["TG_BOT_TOKEN"]
TRAVIS = "6985623877"
HIRES  = "-5306696575"

def send_tg(chat_id, text):
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    subprocess.run([
        "curl", "-s", "--max-time", "10", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        "-H", "Content-Type: application/json", "-d", payload
    ], capture_output=True, text=True)

queue = {}
if os.path.exists(QUEUE_FILE):
    try:
        queue = json.load(open(QUEUE_FILE))
    except:
        queue = {}

NOW = time.time()
STALE_THRESHOLD = 3 * 24 * 3600  # 3 days

stage_labels = {
    0: "Queued (text not sent yet)",
    1: "Sent intro — waiting for reply",
    2: "Qualifying (sales exp / transport)",
    3: "Income reality check",
    4: "Interview confirmation pending",
    5: "CONFIRMED ✅",
    99: "Wants call — human needed",
}

total        = len(queue)
confirmed    = []
stale        = []
by_stage     = {}
opted_out    = 0
website_leads = 0

for lid, lead in queue.items():
    if lead.get("opted_out"):
        opted_out += 1
        continue

    stage = lead.get("stage", 0)
    done  = lead.get("done", False)
    name  = lead.get("name", "Unknown")
    phone = lead.get("phone", "")
    qat   = lead.get("queued_at", NOW)
    src   = lead.get("source", "facebook")

    if src == "website":
        website_leads += 1

    if lead.get("confirmed"):
        confirmed.append(f"{name} ({phone}) — {lead.get('interview_day', 'TBD')}")
        continue

    by_stage[stage] = by_stage.get(stage, [])
    by_stage[stage].append(name)

    # Stale: not done, not opted out, queued 3+ days ago, still waiting
    if not done and stage in (1, 2, 3) and (NOW - qat) > STALE_THRESHOLD:
        stale.append(f"{name} ({phone}) — stage {stage}, {int((NOW-qat)/3600)}h ago")

# Build report
week = datetime.now(timezone(timedelta(hours=-4))).strftime("%b %d")
lines = [f"<b>📊 RECRUITING PIPELINE — Week of {week}</b>\n"]
lines.append(f"Total applicants: <b>{total}</b>")
lines.append(f"🌐 From website form: {website_leads}")
lines.append(f"❌ Opted out / not interested: {opted_out}")
lines.append("")

if confirmed:
    lines.append(f"<b>✅ CONFIRMED INTERVIEWS ({len(confirmed)})</b>")
    for c in confirmed:
        lines.append(f"  • {c}")
    lines.append("")

lines.append("<b>PIPELINE BY STAGE</b>")
for s in sorted(by_stage.keys()):
    label = stage_labels.get(s, f"Stage {s}")
    names = by_stage[s]
    lines.append(f"  [{label}] — {len(names)} people")
    for n in names[:5]:  # cap at 5 per stage to keep it readable
        lines.append(f"    · {n}")
    if len(names) > 5:
        lines.append(f"    ... +{len(names)-5} more")
lines.append("")

if stale:
    lines.append(f"<b>⚠️ STALE LEADS — need manual follow-up ({len(stale)})</b>")
    for s in stale[:8]:
        lines.append(f"  • {s}")
    lines.append("")

# Action items
lines.append("<b>ACTION ITEMS THIS WEEK</b>")
needs_call = [l for l in queue.values() if l.get("stage") == 99 and not l.get("done")]
if needs_call:
    lines.append(f"  📞 {len(needs_call)} people asked for a call — call them now")
if stale:
    lines.append(f"  💬 {len(stale)} stale leads — send Version C text manually")
lines.append("  📋 Run group interviews Tue + Thu 10am")
lines.append("  🔄 Refresh Craigslist posting this week ($25)")
lines.append("  📊 Check Facebook ad spend in Ads Manager")

msg = "\n".join(lines)
send_tg(TRAVIS, msg)
