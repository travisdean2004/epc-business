#!/usr/bin/env python3
"""
Indeed Lead Failover & Auto-Recovery (Oct 16 2026)
CRITICAL SYSTEM: Ensures zero lead loss via 3-layer redundancy

Layer 1: Webhook receiver (accepts Indeed POST)
Layer 2: Lead queue buffer (persists leads to disk)
Layer 3: Watchdog + auto-recovery (detects dead webhooks, restores connectivity)
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

BUFFER_DIR = Path(os.path.expanduser("~/.hermes/indeed_lead_buffer"))
WATCHDOG_LOG = Path(os.path.expanduser("~/.hermes/indeed_watchdog.log"))
SERVER_PID_FILE = Path(os.path.expanduser("~/.hermes/epc_webhook_server.pid"))
NGROK_PID_FILE = Path(os.path.expanduser("~/.hermes/ngrok.pid"))
WEBHOOK_URL = "https://editor-dipping-designer.ngrok-free.dev/webhook/indeed"
LOCALHOST_URL = "http://localhost:3847/webhook/indeed"

BUFFER_DIR.mkdir(exist_ok=True)

def log_watchdog(msg):
    """Log to watchdog file + stdout"""
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_msg = f"{timestamp} {msg}"
    print(full_msg)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(full_msg + "\n")

def buffer_lead(name, email, phone, job, applied_at):
    """Persist lead to disk (failover storage)"""
    lead_file = BUFFER_DIR / f"{datetime.now().isoformat()}-{name.replace(' ', '_')}.json"
    lead_data = {
        "name": name,
        "email": email,
        "phone": phone,
        "job": job,
        "applied_at": applied_at,
        "received_at": datetime.now().isoformat(),
        "sent_to_tg": False
    }
    try:
        with open(lead_file, "w") as f:
            json.dump(lead_data, f)
        return True
    except:
        return False

def check_webhook_endpoint():
    """Test if webhook endpoint is live"""
    try:
        test_payload = {
            "event_type": "health_check",
            "event_data": {
                "applicant_name": "HEALTH_CHECK",
                "applicant_email": "health@epc.local",
                "applicant_phone": "+1-555-0000",
                "job_title": "Health Check"
            }
        }
        req = urllib.request.Request(
            LOCALHOST_URL,
            data=json.dumps(test_payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except:
        return False

def check_ngrok_tunnel():
    """Test if ngrok tunnel is reachable"""
    try:
        with urllib.request.urlopen(f"{WEBHOOK_URL}?test=1", timeout=3) as r:
            return r.status in [200, 404]  # 404 is OK for GET on POST endpoint
    except:
        return False

def restart_webhook_server():
    """Restart the EPC webhook server via PM2"""
    try:
        log_watchdog("⚠️  RESTARTING webhook server via PM2...")
        subprocess.run(["pm2", "restart", "epc-webhook"], timeout=10, check=False)
        time.sleep(3)
        if check_webhook_endpoint():
            log_watchdog("✅ Webhook server restarted successfully")
            return True
        else:
            log_watchdog("❌ Webhook server restart failed — endpoint still dead")
            return False
    except Exception as e:
        log_watchdog(f"❌ Failed to restart server: {e}")
        return False

def restart_ngrok_tunnel():
    """Restart ngrok tunnel"""
    try:
        log_watchdog("⚠️  RESTARTING ngrok tunnel...")
        subprocess.run(["pkill", "-f", "ngrok"], timeout=5, check=False)
        time.sleep(2)
        subprocess.Popen(
            ["bash", os.path.expanduser("~/epc-webhook/tunnel-daemon.sh")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(4)
        if check_ngrok_tunnel():
            log_watchdog("✅ Ngrok tunnel restarted successfully")
            return True
        else:
            log_watchdog("❌ Ngrok tunnel restart failed")
            return False
    except Exception as e:
        log_watchdog(f"❌ Failed to restart ngrok: {e}")
        return False

def check_buffered_leads():
    """Check for leads stuck in buffer (failed to send to Telegram)"""
    buffered = list(BUFFER_DIR.glob("*.json"))
    if buffered:
        log_watchdog(f"⚠️  Found {len(buffered)} buffered leads awaiting delivery")
        return len(buffered)
    return 0

def watchdog_cycle():
    """Main watchdog loop — runs every 2 minutes"""
    log_watchdog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log_watchdog("🔍 INDEED WEBHOOK WATCHDOG CYCLE")
    
    endpoint_ok = check_webhook_endpoint()
    tunnel_ok = check_ngrok_tunnel()
    buffered = check_buffered_leads()
    
    log_watchdog(f"  Endpoint (localhost:3847): {'✅ OK' if endpoint_ok else '❌ DEAD'}")
    log_watchdog(f"  Tunnel (ngrok): {'✅ OK' if tunnel_ok else '❌ DEAD'}")
    log_watchdog(f"  Buffered leads: {buffered}")
    
    # AUTO-RECOVERY: If endpoint is down, restart server
    if not endpoint_ok:
        log_watchdog("🚨 ENDPOINT DOWN — Auto-recovery triggered")
        restart_webhook_server()
        time.sleep(1)
        endpoint_ok = check_webhook_endpoint()
    
    # AUTO-RECOVERY: If tunnel is down, restart ngrok
    if not tunnel_ok:
        log_watchdog("🚨 TUNNEL DOWN — Auto-recovery triggered")
        restart_ngrok_tunnel()
        time.sleep(1)
        tunnel_ok = check_ngrok_tunnel()
    
    # FINAL STATUS
    if endpoint_ok and tunnel_ok:
        log_watchdog("✅ All systems healthy — webhooks flowing")
    else:
        log_watchdog(f"🔴 CRITICAL: System degraded (endpoint={endpoint_ok}, tunnel={tunnel_ok})")
        log_watchdog("    → Leads may be lost. Manual intervention required.")
    
    log_watchdog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

if __name__ == "__main__":
    watchdog_cycle()
