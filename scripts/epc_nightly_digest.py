#!/usr/bin/env python3
"""
EPC Nightly Digest — end-of-day snapshot with real numbers.
Runs 8PM Mon-Sat. no_agent=True. Silent if nothing changed.
"""
import json, os, re, urllib.request, urllib.parse, urllib.error
from datetime import date, timedelta

CRM_PATH = os.path.expanduser("~/epc-webhook/crm-leads.json")
AD_ACCOUNT = "act_20032154"
STATE_FILE = os.path.expanduser("~/.hermes/epc_nightly_state.json")

def get_token():
    try:
        with open(os.path.expanduser("~/.hermes/scripts/epc_lead_notifier.py")) as f:
            src = f.read()
        m = re.search(r'TOKEN\s*=\s*["\']([A-Za-z0-9]+)["\']', src)
        if m:
            return m.group(1)
    except:
        pass
    return ""

def api_get(url):
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read()).get("error", {}).get("message", "HTTP error")
    except Exception as ex:
        return None, str(ex)

def get_today_insights(token):
    params = urllib.parse.urlencode({
        "fields": "spend,impressions,clicks,ctr,actions",
        "date_preset": "this_month",
        "time_increment": "1",
        "access_token": token
    })
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT}/insights?{params}"
    data, err = api_get(url)
    if err or not data:
        return None, err
    rows = data.get("data", [])
    if not rows:
        return None, "no rows"
    rows.sort(key=lambda r: r.get("date_start", ""))
    return rows[-1], None  # most recent day

def extract_leads(actions):
    if not actions:
        return 0
    return int(next((a["value"] for a in actions if a["action_type"] == "lead"), 0))

def get_crm_snapshot():
    try:
        with open(CRM_PATH) as f:
            leads = json.load(f)
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        total = len(leads)
        statuses = {}
        for lead in leads:
            s = lead.get("status", "new_lead")
            statuses[s] = statuses.get(s, 0) + 1

        # Leads that came in today
        new_today = [l for l in leads if l.get("created_time", "").startswith(today)]
        new_yesterday = [l for l in leads if l.get("created_time", "").startswith(yesterday)]

        uncalled = statuses.get("new_lead", 0)
        called = sum(v for k, v in statuses.items() if "called" in k or "contacted" in k)
        appt = sum(v for k, v in statuses.items() if "appt" in k or "appointment" in k)
        closed = sum(v for k, v in statuses.items() if "closed" in k or "sold" in k or "install" in k)

        return {
            "total": total,
            "new_today": len(new_today),
            "new_today_names": [l.get("full_name", "Unknown") for l in new_today[:3]],
            "new_yesterday": len(new_yesterday),
            "uncalled": uncalled,
            "called": called,
            "appt": appt,
            "closed": closed,
            "statuses": statuses
        }
    except Exception as e:
        return {"error": str(e)}

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def main():
    today_str = date.today().strftime("%A, %b %-d")
    token = get_token()
    prev_state = load_state()

    crm = get_crm_snapshot()
    if "error" in crm:
        print(f"⚠️ EPC Nightly: CRM read error — {crm['error']}")
        return

    # Ad data (best effort)
    ad_row = None
    ad_spend = ad_leads = ad_ctr = None
    if token:
        ad_row, _ = get_today_insights(token)
        if ad_row:
            ad_spend = float(ad_row.get("spend", 0))
            ad_ctr = float(ad_row.get("ctr", 0))
            ad_leads = extract_leads(ad_row.get("actions", []))

    # Compare to yesterday's state for changes
    prev_total = prev_state.get("total", crm["total"])
    prev_uncalled = prev_state.get("uncalled", crm["uncalled"])
    prev_appt = prev_state.get("appt", crm["appt"])
    prev_closed = prev_state.get("closed", crm["closed"])

    new_leads_since_last = crm["total"] - prev_total
    appt_delta = crm["appt"] - prev_appt
    closed_delta = crm["closed"] - prev_closed

    # Save state
    save_state({
        "total": crm["total"],
        "uncalled": crm["uncalled"],
        "appt": crm["appt"],
        "closed": crm["closed"],
        "date": date.today().isoformat()
    })

    # Build message
    lines = [f"🌙 **EPC End of Day — {today_str}**", ""]

    # Lead pipeline
    lines.append("**Pipeline:**")
    lines.append(f"• Total leads: {crm['total']} | Uncalled: **{crm['uncalled']}** | Appts: {crm['appt']} | Closed: {crm['closed']}")

    if new_leads_since_last > 0:
        lines.append(f"• +{new_leads_since_last} new leads today")

    if appt_delta > 0:
        lines.append(f"• ✅ +{appt_delta} appointment{'s' if appt_delta > 1 else ''} set today")
    elif appt_delta < 0:
        lines.append(f"• –{abs(appt_delta)} appointments fell off today")

    if closed_delta > 0:
        lines.append(f"• 🏆 +{closed_delta} CLOSE{'S' if closed_delta > 1 else ''} today!")

    # Uncalled warning
    if crm["uncalled"] > 8:
        lines.append(f"• 🚨 {crm['uncalled']} leads sitting uncalled — that's real money going cold")
    elif crm["uncalled"] > 3:
        lines.append(f"• ⚠️ {crm['uncalled']} leads still uncalled")

    # Ads section
    lines.append("")
    if ad_spend is not None and ad_spend > 0:
        ad_cpl = round(ad_spend / ad_leads, 2) if ad_leads else None
        lines.append(f"**Ads (latest day):**")
        lines.append(f"• ${ad_spend:.2f} spent | {ad_leads} leads | CPL {'$' + str(ad_cpl) if ad_cpl else 'N/A'} | CTR {ad_ctr:.2f}%")
    else:
        lines.append("**Ads:** no spend data for today yet")

    # Closing call-to-action if needed
    if crm["uncalled"] > 0:
        lines.append("")
        lines.append(f"📞 **{crm['uncalled']} leads need a call. First one in the morning wins.**")

    print("\n".join(lines))

if __name__ == "__main__":
    main()
