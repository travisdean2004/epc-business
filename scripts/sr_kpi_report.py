#!/usr/bin/env python3
"""SalesRabbit KPI Report — doors knocked, activity, slacker detection"""
import json, urllib.request, urllib.error, sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

KEY = open("/Users/tdizzlewizzle/.hermes/salesrabbit_api_key.txt").read().strip()
HEADERS = {"Authorization": f"Bearer {KEY}"}
BASE = "https://api.salesrabbit.com"

def sr_get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# Fetch all leads (paginated)
leads = []
page = 1
while True:
    data = sr_get(f"/leads?limit=2000&page={page}")
    batch = data.get("data", [])
    leads.extend(batch)
    meta = data.get("meta", {})
    if not meta.get("morePages", False):
        break
    page += 1

now = datetime.now(timezone.utc)
today = now.date()
yesterday = today - timedelta(days=1)
week_ago = today - timedelta(days=7)
two_weeks_ago = today - timedelta(days=14)

def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None

# Per-rep stats
rep_stats = defaultdict(lambda: {
    "total": 0,
    "today": 0,
    "yesterday": 0,
    "7d": 0,
    "14d": 0,
    "last_active": None,
    "statuses_today": defaultdict(int),
    "statuses_7d": defaultdict(int),
    "sats_7d": 0,
    "leads_7d": 0,
    "closes_7d": 0,
})

for lead in leads:
    rep = (lead.get("userName") or "").strip()
    if not rep:
        continue
    
    created = parse_dt(lead.get("dateCreated"))
    modified = parse_dt(lead.get("statusModified") or lead.get("dateModified"))
    status = (lead.get("status") or "").strip()
    
    # Use most recent of created/modified as the activity date
    activity_dt = modified or created
    if not activity_dt:
        continue
    
    activity_date = activity_dt.date()
    s = rep_stats[rep]
    s["total"] += 1
    
    # Update last active
    if s["last_active"] is None or activity_date > s["last_active"]:
        s["last_active"] = activity_date
    
    # Window counts — using statusModified as "activity" indicator
    if activity_date == today:
        s["today"] += 1
        s["statuses_today"][status] += 1
    if activity_date == yesterday:
        s["yesterday"] += 1
    if activity_date >= week_ago:
        s["7d"] += 1
        s["statuses_7d"][status] += 1
        if "sat" in status.lower() or "close" in status.lower():
            s["sats_7d"] += 1
        if status.lower() in ("lead", "1st", "2nd", "3rd", "go back", "tonight"):
            s["leads_7d"] += 1
    if activity_date >= two_weeks_ago:
        s["14d"] += 1

# Build report
lines = []
lines.append(f"📊 *EPC SalesRabbit KPI Report*")
lines.append(f"📅 {today.strftime('%A, %B %d %Y')} | {len(leads)} total pins\n")

# Sort by 7d activity desc
sorted_reps = sorted(rep_stats.items(), key=lambda x: -x[1]["7d"])

active_today = [(r, s) for r, s in sorted_reps if s["today"] > 0]
active_week = [(r, s) for r, s in sorted_reps if s["7d"] > 0 and s["today"] == 0]
inactive = [(r, s) for r, s in sorted_reps if s["7d"] == 0]

# TODAY's workers
if active_today:
    lines.append("🟢 *Working Today*")
    for rep, s in active_today:
        last = s["last_active"].strftime("%m/%d") if s["last_active"] else "?"
        status_str = ", ".join(f"{v}x {k}" for k, v in sorted(s["statuses_today"].items(), key=lambda x: -x[1]))
        lines.append(f"  • *{rep}* — {s['today']} pins today | {s['7d']}wk | {status_str}")
else:
    lines.append("🔴 *Nobody logged activity today yet*")

lines.append("")

# Active this week but not today
if active_week:
    lines.append("🟡 *Active This Week (not today)*")
    for rep, s in active_week[:10]:
        last = s["last_active"].strftime("%m/%d") if s["last_active"] else "?"
        lines.append(f"  • *{rep}* — {s['7d']}wk | last active {last}")
    if len(active_week) > 10:
        lines.append(f"  ... +{len(active_week)-10} more")

lines.append("")

# Slackers
if inactive:
    lines.append(f"🔴 *Zero Activity Last 7 Days ({len(inactive)} reps)*")
    # Show ones who had recent history (last 30d)
    recent_ghosts = [(r, s) for r, s in inactive if s["14d"] > 0]
    real_ghosts = [(r, s) for r, s in inactive if s["14d"] == 0 and s["total"] > 0]
    
    if recent_ghosts:
        lines.append("  *(had activity 8-14 days ago — going ghost):*")
        for rep, s in recent_ghosts:
            last = s["last_active"].strftime("%m/%d") if s["last_active"] else "?"
            lines.append(f"  ⚠️ {rep} — last active {last}")
    
    lines.append(f"  *(completely inactive — {len(real_ghosts)} reps with 0 pins in 14d)*")

print("\n".join(lines))
