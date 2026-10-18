#!/usr/bin/env python3
import json
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
import asyncio

STATE_FILE = Path.home() / ".hermes" / "indeed_weekend_leads.json"
TG_CHAT_ID = "-5306696575"  # EPC HOT LEADS
TG_BOT_TOKEN = ""

def load_config():
    global TG_BOT_TOKEN
    cfg_path = Path.home() / "epc-webhook" / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.load(open(cfg_path))
            TG_BOT_TOKEN = cfg.get("TG_BOT_TOKEN", "")
        except:
            pass

def is_weekend():
    weekday = datetime.now().weekday()
    return weekday in [5, 6]

def load_seen():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}

def save_seen(seen):
    STATE_FILE.write_text(json.dumps(seen, indent=2))

def send_to_tg(name, phone, email, applied_when):
    msg = f"🔥 <b>INDEED WEEKEND LEAD</b>\n"
    msg += f"<b>{name}</b>\n"
    if phone:
        msg += f"📞 <code>{phone}</code>\n"
    if email:
        msg += f"📧 {email}\n"
    msg += f"📅 Applied: {applied_when}\n"
    msg += f"💼 <b>CALL IMMEDIATELY!</b>"
    
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        "-d", f"chat_id={TG_CHAT_ID}",
        "-d", f"text={msg}",
        "-d", "parse_mode=HTML"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=8)
        return b'"ok":true' in result.stdout
    except:
        return False

async def scrape_indeed_cdp():
    try:
        ws_result = subprocess.check_output('curl -s http://localhost:9222/json/version', shell=True)
        ws_data = json.loads(ws_result)
        ws_url = ws_data.get("webSocketDebuggerUrl", "")
        
        if not ws_url:
            return []
        
        sys.path.insert(0, str(Path.home() / "epc"))
        try:
            from desktop_auto import RawCDP
        except ImportError:
            return []
        
        applicants = []
        async with RawCDP.new_tab() as cdp:
            await cdp.goto("https://employers.indeed.com/candidates?id=6186a8e3e50c&tab=manage", wait_ms=5000)
            result = await cdp.cmd("Runtime.evaluate", expression='''
            (() => {
                let applicants = [];
                let rows = document.querySelectorAll('[data-testid="candidate-row"]');
                rows.forEach(row => {
                    try {
                        let name_el = row.querySelector('[data-testid="candidate-name"]');
                        let email_el = row.querySelector('[data-testid="candidate-email"]');
                        let phone_el = row.querySelector('[data-testid="candidate-phone"]');
                        let time_el = row.querySelector('[data-testid="applied-date"]');
                        
                        let name = name_el ? name_el.innerText.trim() : '';
                        let email = email_el ? email_el.innerText.trim() : '';
                        let phone = phone_el ? phone_el.innerText.trim() : '';
                        let applied = time_el ? time_el.innerText.trim() : 'Unknown';
                        
                        if (name && (email || phone)) {
                            applicants.push({name, email, phone, applied});
                        }
                    } catch (e) {}
                });
                return applicants;
            })()
            ''')
            if result and result.get("value"):
                applicants = result["value"]
        
        return applicants
    except Exception as e:
        return []

def main():
    load_config()
    
    if not TG_BOT_TOKEN:
        return
    
    if not is_weekend() and "TEST" not in sys.argv:
        return
    
    print(f"[indeed] Scanning for weekend leads...")
    
    try:
        applicants = asyncio.run(scrape_indeed_cdp())
    except:
        applicants = []
    
    if not applicants:
        print("[indeed] No leads found")
        return
    
    seen = load_seen()
    new_count = 0
    
    for app in applicants:
        name = app.get("name", "").strip()
        email = app.get("email", "").strip()
        phone = app.get("phone", "").strip()
        applied = app.get("applied", "Unknown").strip()
        
        if not name or (not email and not phone):
            continue
        
        key = f"{name}|{email}".lower()
        if key in seen:
            continue
        
        if send_to_tg(name, phone, email, applied):
            print(f"✅ {name}")
            seen[key] = datetime.now().isoformat()
            new_count += 1
    
    save_seen(seen)
    print(f"[indeed] Posted {new_count} weekend leads")

if __name__ == "__main__":
    main()
