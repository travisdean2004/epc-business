#!/usr/bin/env python3
"""2pm slacker alert — only fires if active reps haven't logged anything today"""
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

# Only alert about reps who were active in last 7 days but haven't touched SR today
mia = [(r, rep_7d[r], rep_last[r]) for r in rep_7d if rep_7d[r] >= 5 and rep_today.get(r, 0) == 0]
mia.sort(key=lambda x: -x[1])

# Don't send if everyone's working
if not mia:
    # Silent — print nothing so no message is delivered
    pass
else:
    lines = [f"⚠️ *2pm Slacker Alert — {today.strftime('%a %b %d')}*\n"]
    lines.append(f"These reps were active last 7 days but have *zero pins today*:\n")
    for rep, wk, last in mia:
        lines.append(f"  🔴 *{rep}* — {wk} pins/wk | last active {last.strftime('%m/%d')}")
    lines.append(f"\n({len([r for r in rep_today if rep_today[r] > 0])} reps ARE working today)")
    print("\n".join(lines))
