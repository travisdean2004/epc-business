#!/usr/bin/env python3
"""
EPC Token Watchdog
Tests the Telegram bot token and Twilio credentials every 30 min.
If broken: auto-heals from .env, restarts webhook, alerts Travis.
Also checks for lead gaps (FB count vs seen list).
"""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

CONFIG_PATH = os.path.expanduser("~/epc-webhook/config.json")
ENV_PATH    = os.path.expanduser("~/epc-webhook/.env")
SEEN_FILE   = os.path.expanduser("~/.hermes/epc_recruiting_seen_leads.txt")
TRAVIS_ID   = "6985623877"
NEW_HIRES   = "-5306696575"

def load_env():
    env = {}
    try:
        for line in open(ENV_PATH).read().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    except:
        pass
    return env

def load_config():
    return json.load(open(CONFIG_PATH))

def save_config(cfg):
    json.dump(cfg, open(CONFIG_PATH, 'w'), indent=2)

def test_token(bot_token):
    """Returns True if token is valid via getMe (no message sent)."""
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "10",
            f"https://api.telegram.org/bot{bot_token}/getMe"
        ], capture_output=True, text=True)
        result = json.loads(r.stdout) if r.stdout.strip() else {}
        return result.get("ok", False), result.get("description", "")
    except Exception as e:
        return False, str(e)

def test_twilio(sid, token, from_num):
    """Test Twilio account validity via Account API."""
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "10",
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            "-u", f"{sid}:{token}"
        ], capture_output=True, text=True)
        data = json.loads(r.stdout) if r.stdout.strip() else {}
        return data.get("sid") == sid, data.get("status", "unknown")
    except Exception as e:
        return False, str(e)

def send_via_hermes(text):
    """Write alert to a file for Hermes cron to pick up and deliver."""
    alert_path = os.path.expanduser("~/.hermes/epc_token_alert.txt")
    with open(alert_path, 'w') as f:
        f.write(text)
    # Also print so Hermes cron (no_agent=false) can deliver
    print(text)

def restart_webhook():
    subprocess.run(["pm2", "restart", "epc-webhook"], capture_output=True)

def check_lead_gap(config):
    """Compare FB lead count vs seen leads. Return gap count."""
    page_token = config.get('PAGE_ACCESS_TOKEN', '')
    form_ids = config.get('RECRUIT_FORM_IDS', ['1036750986029192', '1763068848451143'])
    
    seen = set()
    if os.path.exists(SEEN_FILE):
        seen = set(l.strip() for l in open(SEEN_FILE) if l.strip())
    
    missed = []
    for form_id in form_ids:
        try:
            r = subprocess.run(["curl", "-s", "--max-time", "15",
                f"https://graph.facebook.com/v19.0/{form_id}/leads?fields=id,created_time,field_data&limit=25&access_token={page_token}"
            ], capture_output=True, text=True)
            data = json.loads(r.stdout).get("data", [])
            cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            for lead in data:
                if lead['id'] in seen:
                    continue
                lead_dt = datetime.fromisoformat(lead['created_time'].replace('+0000', '+00:00'))
                if lead_dt > cutoff:
                    missed.append(lead)
        except:
            pass
    return missed

def deliver_missed_leads(bot_token, missed_leads, config):
    """Send missed leads to NEW HIRES."""
    page_token = config.get('PAGE_ACCESS_TOKEN', '')
    delivered = []
    for lead in missed_leads:
        fd = {f['name']: f['values'][0] for f in lead.get('field_data', []) if f.get('values')}
        name  = fd.get('full_name', '?')
        phone = fd.get('phone_number', '?')
        email = fd.get('email', '')
        dt = datetime.fromisoformat(lead['created_time'].replace('+0000', '+00:00'))
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        time_str = et.strftime("%b %d at %I:%M %p ET")

        msg = f"🧑‍💼 RECOVERED LEAD (missed earlier)\n👤 {name}\n📞 {phone}"
        if email: msg += f"\n📧 {email}"
        msg += f"\n🕐 {time_str}\n📲 Call within 5 minutes!"

        payload = json.dumps({"chat_id": NEW_HIRES, "text": msg})
        r = subprocess.run(["curl", "-s", "--max-time", "10", "-X", "POST",
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            "-H", "Content-Type: application/json", "-d", payload
        ], capture_output=True, text=True)
        if json.loads(r.stdout).get("ok"):
            delivered.append(lead['id'])
            with open(SEEN_FILE, 'a') as f:
                f.write(lead['id'] + '\n')
    return delivered

# ── MAIN ──────────────────────────────────────────────────────────────────────
config = load_config()
current_tg = config.get('TG_BOT_TOKEN', '')
current_twilio_sid = config.get('TWILIO_SID', '')
current_twilio_tok = config.get('TWILIO_TOKEN', '')
current_twilio_from = config.get('TWILIO_FROM', '')

# ── TEST TELEGRAM ──
ok_tg, desc_tg = test_token(current_tg)

if not ok_tg:
    env = load_env()
    fallback_tg = env.get('TELEGRAM_BOT_TOKEN', '')
    healed_tg = False

    if fallback_tg and fallback_tg != current_tg:
        ok2, _ = test_token(fallback_tg)
        if ok2:
            config['TG_BOT_TOKEN'] = fallback_tg
            save_config(config)
            restart_webhook()
            healed_tg = True
            print(f"🔧 TG TOKEN AUTO-HEALED — webhook restarted. ({datetime.now().strftime('%b %d %I:%M %p')})")
        
    if not healed_tg:
        print(f"🚨 TG BOT TOKEN BROKEN — auto-heal failed. Leads are NOT being delivered to Telegram.")
        sys.exit(1)

# ── TEST TWILIO ──
ok_twilio, desc_twilio = test_twilio(current_twilio_sid, current_twilio_tok, current_twilio_from)

if not ok_twilio:
    print(f"🚨 TWILIO ACCOUNT BROKEN — status: {desc_twilio}. Recruit texts are NOT being sent. Check account balance, A2P compliance, or token expiry.")
    # Don't exit — TG is more critical, but alert Travis that texts are down
else:
    # Twilio OK, silent
    pass

# ── LEAD GAP CHECK ────────────────────────────────────────────────────────────
active_tg = config.get('TG_BOT_TOKEN', current_tg)
missed = check_lead_gap(config)
if missed:
    delivered = deliver_missed_leads(active_tg, missed, config)
    print(f"⚠️ Recovered {len(delivered)} missed lead(s) and delivered to NEW HIRES.")
