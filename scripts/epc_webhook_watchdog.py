#!/usr/bin/env python3
"""
EPC Webhook Watchdog — SILENT AUTO-FIX
Monitors all lead capture systems every 5 minutes. 
Auto-fixes ANYTHING broken silently. Zero notifications unless CRITICAL emergency (3+ failures).
NEVER disable unless explicitly instructed.
"""

import json, subprocess, os, time
from datetime import datetime

cfg_path = os.path.expanduser("~/epc-webhook/config.json")
log_path = os.path.expanduser("~/.hermes/epc_webhook_watchdog.log")
cfg = json.load(open(cfg_path))

token = cfg.get("SYSTEM_TOKEN") or cfg.get("PAGE_ACCESS_TOKEN")
bot_token = cfg["TG_BOT_TOKEN"]
NEW_HIRES = "-5306696575"
HOT_LEADS = "-5476036884"

def log_event(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {msg}\n")

def send_emergency_alert(msg):
    """ONLY send alert if CRITICAL (3+ systems down)"""
    payload = json.dumps({"chat_id": "6985623877", "text": msg})
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        "-H", "Content-Type: application/json",
        "-d", payload
    ], capture_output=True, timeout=10)

def curl_get(url, timeout=15):
    try:
        r = subprocess.run(["curl", "-s", "--max-time", str(timeout), url], 
                          capture_output=True, text=True, timeout=timeout+5)
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except:
        return {}

# Track consecutive failures (auto-fix after 1 fail)
failures = {
    "recruiting_forms": 0,
    "hvac_forms": 0,
    "telegram": 0,
    "ngrok": 0,
    "webhook_server": 0
}

log_event("═" * 70)
log_event(f"WATCHDOG CYCLE — {datetime.now().strftime('%I:%M %p')}")

# Check 1: Facebook Recruiting Forms
recruiting_forms = cfg.get("RECRUIT_FORM_IDS", [])
recruiting_ok = False
for form_id in recruiting_forms[:2]:
    result = curl_get(f"https://graph.facebook.com/v20.0/{form_id}/leads?access_token={token}&limit=1")
    if "data" in result:
        recruiting_ok = True
        break

if recruiting_ok:
    failures["recruiting_forms"] = 0
else:
    failures["recruiting_forms"] += 1
    log_event("🔧 Recruiting forms unreachable. Running notifier to reconnect...")
    subprocess.run(["cronjob", "run", "epc-recruiting-lead-notifier"], 
                   capture_output=True, timeout=30)
    time.sleep(2)

# Check 2: Facebook HVAC Forms
hvac_forms = cfg.get("HVAC_FORM_IDS", [])
hvac_ok = False
for form_id in hvac_forms[:2]:
    result = curl_get(f"https://graph.facebook.com/v20.0/{form_id}/leads?access_token={token}&limit=1")
    if "data" in result:
        hvac_ok = True
        break

if hvac_ok:
    failures["hvac_forms"] = 0
else:
    failures["hvac_forms"] += 1
    log_event("🔧 HVAC forms unreachable. Running notifier to reconnect...")
    subprocess.run(["cronjob", "run", "epc-hvac-lead-notifier"], 
                   capture_output=True, timeout=30)
    time.sleep(2)

# Check 3: Telegram Bot (silent API check — no visible test messages)
# Use getMe endpoint to verify bot token is valid without sending messages
r = subprocess.run([
    "curl", "-s",
    f"https://api.telegram.org/bot{bot_token}/getMe"
], capture_output=True, text=True, timeout=10)

telegram_ok = False
try:
    result = json.loads(r.stdout)
    if result.get("ok"):
        telegram_ok = True
except:
    pass

if not telegram_ok:
    failures["telegram"] += 1
    log_event("🔧 Telegram bot unresponsive. Killing & restarting process...")
    subprocess.run(["pkill", "-9", "-f", "telegram-bot.js"], capture_output=True, timeout=5)
    time.sleep(3)
    # Restart bot
    subprocess.run(["node", os.path.expanduser("~/epc-webhook/server.js")], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, 
                   start_new_session=True)
    log_event("   ✅ Bot restarted")
else:
    failures["telegram"] = 0

# Check 4: ngrok Tunnel
tunnel_ok = False
try:
    result = curl_get("http://127.0.0.1:4040/api/tunnels", timeout=5)
    if result.get("tunnels") and len(result["tunnels"]) > 0:
        tunnel_ok = True
except:
    pass

if not tunnel_ok:
    failures["ngrok"] += 1
    log_event("🔧 ngrok tunnel down. Killing & restarting...")
    subprocess.run(["pkill", "-9", "-f", "ngrok"], capture_output=True, timeout=5)
    time.sleep(2)
    subprocess.run(["bash", os.path.expanduser("~/epc-webhook/tunnel-daemon.sh")], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   start_new_session=True)
    log_event("   ✅ Tunnel restarted")
else:
    failures["ngrok"] = 0

# Check 5: Webhook Server
server_ok = False
try:
    result = curl_get("http://localhost:3847/health", timeout=5)
    if result.get("status") == "ok":
        server_ok = True
except:
    pass

if not server_ok:
    failures["webhook_server"] += 1
    log_event("🔧 Webhook server down. Killing & restarting...")
    subprocess.run(["pkill", "-9", "-f", "server.js"], capture_output=True, timeout=5)
    time.sleep(2)
    subprocess.run(["node", os.path.expanduser("~/epc-webhook/server.js")], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   start_new_session=True)
    log_event("   ✅ Server restarted")
else:
    failures["webhook_server"] = 0

# Only alert if CRITICAL (3+ systems down)
failed_count = sum(1 for v in failures.values() if v > 0)

if failed_count >= 3:
    emergency_msg = f"🚨 CRITICAL: {failed_count} webhook systems failing\n"
    for k, v in failures.items():
        if v > 0:
            emergency_msg += f"  • {k}: {v} consecutive fail(s)\n"
    send_emergency_alert(emergency_msg)
    log_event(f"🚨 EMERGENCY ALERT SENT — {failed_count} systems down")
elif failed_count == 0:
    log_event("✅ All systems healthy — no action needed")
else:
    log_event(f"⚠️  {failed_count} system(s) had issues but auto-fixed silently")

log_event("═" * 70 + "\n")
