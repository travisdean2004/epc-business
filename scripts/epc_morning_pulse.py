#!/usr/bin/env python3
"""
EPC Morning Pulse — Real Meta ad data + CRM pipeline snapshot.
Runs 7AM daily. no_agent=True, stdout delivered directly to Travis.
Silent if nothing meaningful to report.
"""
import json, urllib.request, urllib.parse, urllib.error, re, os
from datetime import date, timedelta

CRM_PATH = os.path.expanduser("~/epc-webhook/crm-leads.json")
AD_ACCOUNT = "act_20032154"

# Pull token from existing script (same source used by lead notifier)
def get_token():
    try:
        with open(os.path.expanduser("~/.hermes/scripts/epc_lead_notifier.py")) as f:
            src = f.read()
        m = re.search(r'TOKEN\s*=\s*["\']([A-Za-z0-9]+)["\']', src)
        if m:
            return m.group(1)
    except:
        pass
    try:
        with open(os.path.expanduser("~/epc-webhook/config.json")) as f:
            cfg = json.load(f)
        return cfg.get("SYSTEM_TOKEN", "")
    except:
        return ""

def api_get(url):
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read()).get("error", {}).get("message", "HTTP error")
    except Exception as ex:
        return None, str(ex)

def get_daily_insights(token):
    """Get daily breakdown for this month — pick the most recent row."""
    params = urllib.parse.urlencode({
        "fields": "spend,impressions,clicks,ctr,actions,date_start",
        "date_preset": "this_month",
        "time_increment": "1",
        "access_token": token
    })
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT}/insights?{params}"
    data, err = api_get(url)
    if err or not data:
        return None, None, err
    rows = data.get("data", [])
    if not rows:
        return None, None, "no data rows"
    # Sort by date, take last 2
    rows.sort(key=lambda r: r.get("date_start", ""))
    return rows[-1], rows[-2] if len(rows) >= 2 else None, None

def get_monthly_totals(token):
    params = urllib.parse.urlencode({
        "fields": "spend,actions",
        "date_preset": "this_month",
        "access_token": token
    })
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT}/insights?{params}"
    data, err = api_get(url)
    if err or not data:
        return None, None, err
    rows = data.get("data", [])
    if not rows:
        return 0, 0, None
    spend = float(rows[0].get("spend", 0))
    actions = rows[0].get("actions", [])
    leads = int(next((a["value"] for a in actions if a["action_type"] == "lead"), 0))
    return spend, leads, None

def get_active_campaign(token):
    params = urllib.parse.urlencode({
        "fields": "name,status,daily_budget,effective_status",
        "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]',
        "access_token": token
    })
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT}/campaigns?{params}"
    data, err = api_get(url)
    if err:
        return [], err
    return data.get("data", []), None

def extract_leads(actions):
    if not actions:
        return 0
    return int(next((a["value"] for a in actions if a["action_type"] == "lead"), 0))

def get_crm_snapshot():
    try:
        with open(CRM_PATH) as f:
            leads = json.load(f)
        total = len(leads)
        statuses = {}
        for lead in leads:
            s = lead.get("status", "new_lead")
            statuses[s] = statuses.get(s, 0) + 1
        uncalled = statuses.get("new_lead", 0)
        called = sum(v for k, v in statuses.items() if "called" in k or "contacted" in k)
        appt = sum(v for k, v in statuses.items() if "appt" in k or "appointment" in k)
        closed = sum(v for k, v in statuses.items() if "closed" in k or "sold" in k or "install" in k)
        return {"total": total, "uncalled": uncalled, "called": called, "appt": appt, "closed": closed}
    except Exception as e:
        return {"error": str(e)}

def main():
    token = get_token()
    if not token:
        print("⚠️ EPC Morning Pulse: no token found — check epc_lead_notifier.py")
        return

    today_str = date.today().strftime("%A, %b %-d")

    # Get ad data
    latest_row, prev_row, err = get_daily_insights(token)
    month_spend, month_leads, _ = get_monthly_totals(token)
    active_camps, camp_err = get_active_campaign(token)

    # Parse latest row
    if latest_row:
        row_date = latest_row.get("date_start", "?")
        spend = float(latest_row.get("spend", 0))
        impressions = int(latest_row.get("impressions", 0))
        ctr = float(latest_row.get("ctr", 0))
        leads = extract_leads(latest_row.get("actions", []))
        cpl = round(spend / leads, 2) if leads > 0 else None

        # Delta vs previous day
        if prev_row:
            prev_leads = extract_leads(prev_row.get("actions", []))
            prev_spend = float(prev_row.get("spend", 0))
            lead_delta = leads - prev_leads
            spend_delta = spend - prev_spend
        else:
            lead_delta = spend_delta = None
    else:
        row_date = spend = impressions = ctr = leads = cpl = None
        lead_delta = spend_delta = None

    crm = get_crm_snapshot()

    # Build flags
    flags = []
    if not active_camps:
        flags.append("🚨 NO ACTIVE CAMPAIGNS — zero spend right now")
    if spend and cpl and cpl > 25:
        flags.append(f"⚠️ CPL ${cpl:.2f} — getting expensive, check targeting")
    if spend and cpl and cpl < 12:
        flags.append(f"🔥 CPL ${cpl:.2f} — ads printing money, consider raising budget")
    if spend and ctr < 1.5:
        flags.append(f"⚠️ CTR {ctr:.2f}% — low click rate, creative may be fatigued")
    if "error" not in crm and crm.get("uncalled", 0) > 5:
        flags.append(f"📞 {crm['uncalled']} leads sitting uncalled in CRM")

    # Build message
    lines = [f"☀️ **EPC Morning Pulse — {today_str}**", ""]

    if latest_row:
        # Format date nicely
        try:
            from datetime import datetime
            d = datetime.strptime(row_date, "%Y-%m-%d")
            row_label = d.strftime("%a %b %-d")
        except:
            row_label = row_date

        lines.append(f"**Ad Performance ({row_label}):**")
        lines.append(f"• Spent: **${spend:.2f}** | Leads: **{leads}** | CPL: {'$' + str(cpl) if cpl else 'N/A'}")
        lines.append(f"• Impressions: {impressions:,} | CTR: {ctr:.2f}%")
        if lead_delta is not None:
            arrow = "▲" if lead_delta > 0 else ("▼" if lead_delta < 0 else "–")
            lines.append(f"• vs prev day: {arrow} {abs(lead_delta)} leads, {'+' if spend_delta >= 0 else ''}{spend_delta:.2f} spend")
    else:
        lines.append("**Ad Performance:** no data available")

    lines.append("")
    if month_spend is not None:
        month_cpl = round(month_spend / month_leads, 2) if month_leads else None
        lines.append(f"**This Month:** ${month_spend:.2f} spent | {month_leads} leads | CPL {'$' + str(month_cpl) if month_cpl else 'N/A'}")

    lines.append("")
    if "error" not in crm:
        lines.append(f"**CRM Pipeline ({crm['total']} leads):**")
        lines.append(f"• Uncalled: {crm['uncalled']} | Called: {crm['called']} | Appts: {crm['appt']} | Closed: {crm['closed']}")
    else:
        lines.append(f"**CRM:** error reading data")

    if flags:
        lines.append("")
        for flag in flags:
            lines.append(flag)

    # Suppress if literally nothing interesting
    has_data = (spend and spend > 0) or (month_spend and month_spend > 0) or ("error" not in crm)
    if not has_data and not flags:
        print("[SILENT]")
        return

    print("\n".join(lines))

if __name__ == "__main__":
    main()
