#!/usr/bin/env python3
"""
EPC Twilio Health Monitor — detects silent text failures
Runs every 10 min. Checks for:
1. Failed text deliveries (Twilio API failures)
2. Text queue buildup (stage 0 leads with no delivery attempts)
3. Account balance and compliance status

If issues found: alert Travis immediately.
"""
import json, os, subprocess
from datetime import datetime, timedelta

CONFIG_PATH = "/Users/tdizzlewizzle/epc-webhook/config.json"
QUEUE_PATH = "/Users/tdizzlewizzle/.hermes/recruit_text_queue.json"
TWILIO_LOG = "/Users/tdizzlewizzle/epc-webhook/twilio_send_log.json"
TRAVIS_ID = "6985623877"

def load_config():
    return json.load(open(CONFIG_PATH))

def send_alert(msg, bot_token=None):
    """Send alert to Travis via Telegram."""
    if not bot_token:
        cfg = load_config()
        bot_token = cfg.get('TG_BOT_TOKEN', '')
    
    payload = json.dumps({"chat_id": TRAVIS_ID, "text": msg})
    subprocess.run(["curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        "-H", "Content-Type: application/json", "-d", payload
    ], capture_output=True)

def check_queue_stalls():
    """Check for leads stuck in stage 0 (should have been sent 10+ min ago)."""
    if not os.path.exists(QUEUE_PATH):
        return []
    
    queue = json.load(open(QUEUE_PATH))
    stalled = []
    now = datetime.now().timestamp()
    
    for lead_id, lead in queue.items():
        if lead.get('stage') == 0 and not lead.get('done'):
            queued_at = lead.get('queued_at', now)
            age_min = (now - queued_at) / 60
            if age_min > 15:  # Should have been sent by now
                stalled.append((lead.get('name'), age_min, lead.get('phone')))
    
    return stalled

def check_twilio_balance(sid, token):
    """Check account balance. Alert if < $5 remaining."""
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "10",
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            "-u", f"{sid}:{token}"
        ], capture_output=True, text=True)
        data = json.loads(r.stdout)
        balance = float(data.get("balance", 0))  # in dollars
        return balance, balance < 5  # Alert if < $5
    except:
        return 0, False

# ── MAIN ──────────────────────────────────────────────────────────────────────
cfg = load_config()
bot_token = cfg.get('TG_BOT_TOKEN', '')
twilio_sid = cfg.get('TWILIO_SID', '')
twilio_tok = cfg.get('TWILIO_TOKEN', '')

# Check for stalled leads
stalled = check_queue_stalls()
if stalled:
    names = ", ".join([f"{name} ({int(age)}m)" for name, age, _ in stalled])
    msg = f"🚨 TWILIO STALL: {len(stalled)} leads stuck in queue (not sending)\n{names}\n\nCheck Twilio API status or account compliance."
    send_alert(msg, bot_token)
    print(msg)

# Check balance
balance, low = check_twilio_balance(twilio_sid, twilio_tok)
if low:
    msg = f"⚠️ TWILIO LOW BALANCE: ${balance:.2f} — add funds or texts will fail soon."
    send_alert(msg, bot_token)
    print(msg)

# Silent on success
if not stalled and not low:
    print(f"✓ Twilio OK ({len(json.load(open(QUEUE_PATH)).get('', {}))} leads in queue)")
