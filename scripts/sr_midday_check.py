#!/usr/bin/env python3
"""Midday SalesRabbit check — who's working, who's not"""
import json, urllib.request
from datetime import datetime, timezone, timedelta
from collections import defaultdict

KEY = open("/Users/tdizzlewizzle/.hermes/salesrabbit_api_key.txt").read().strip()
HEADERS = {"Authorization": f"Bearer {KEY}"}
BASE = "https://api.salesrabbit.com"

def sr_get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

leads = []
page = 1
while True:
    data = sr_get(f"/leads?limit=2000&page={page}")
    leads.extend(data.get("data", []))
    if not data.get("meta", {}).get("morePages", False):
        break
    page += 1

now = datetime.now(timezone.utc)
today = now.date()
week_ago = today - timedelta(days=7)

def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None

rep_today = defaultdict(int)
rep_7d = defaultdict(int)
rep_last = {}

for lead in leads:
    rep = (lead.get("userName") or "").strip()
    if not rep:
        continue
    dt = parse_dt(lead.get("statusModified") or lead.get("dateModified")) or parse_dt(lead.get("dateCreated"))
    if not dt:
        continue
    d = dt.date()
    if rep not in rep_last or d > rep_last[rep]:
        rep_last[rep] = d
    if d == today:
        rep_today[rep] += 1
    if d >= week_ago:
        rep_7d[rep] += 1

working = [(r, rep_today[r]) for r in rep_today if rep_today[r] > 0]
working.sort(key=lambda x: -x[1])

# Who was active last 7d but hasn't pinged today
slacking = [(r, rep_7d[r], rep_last[r]) for r in rep_7d if rep_7d[r] > 0 and rep_today.get(r, 0) == 0]
slacking.sort(key=lambda x: -x[1])

lines = [f"☀️ *Noon Check-In — {today.strftime('%a %b %d')}*\n"]

if working:
    lines.append(f"🟢 *Out knocking ({len(working)} reps)*")
    for rep, cnt in working:
        lines.append(f"  • {rep} — {cnt} pins so far")
else:
    lines.append("🔴 *Nobody has logged pins yet today*")

lines.append("")

if slacking:
    lines.append(f"😴 *Active this week but MIA today ({len(slacking)} reps)*")
    for rep, wk, last in slacking[:8]:
        lines.append(f"  • {rep} — {wk} pins last 7d | last: {last.strftime('%m/%d')}")
    if len(slacking) > 8:
        lines.append(f"  ... +{len(slacking)-8} more")

print("\n".join(lines))
