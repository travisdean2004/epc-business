#!/usr/bin/env python3
"""
EPC Lead Capture Autonomous Monitor — Optimized for speed.
"""

import json
import subprocess
import os
from pathlib import Path

cfg_path = Path.home() / "epc-webhook" / "config.json"
log_path = Path.home() / ".hermes" / "lead_emergency.log"
seen_file = Path.home() / ".hermes" / "epc_autonomous_leads.json"

with open(cfg_path) as f:
    cfg = json.load(f)

token = cfg.get("PAGE_ACCESS_TOKEN") or cfg.get("SYSTEM_TOKEN")
bot_token = cfg["TG_BOT_TOKEN"]
new_hires = "-5306696575"

def send_tg(name, phone, email):
    """Post to Telegram"""
    if not name:
        return
    msg = f"🔥 <b>{name}</b>\n"
    if phone:
        msg += f"📞 <code>{phone}</code>\n"
    if email:
        msg += f"📧 {email}\n"
    msg += "📲 CALL"
    
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        "-d", f"chat_id={new_hires}&text={msg}&parse_mode=HTML"
    ], capture_output=True, timeout=5)

# Load seen
seen = set()
if seen_file.exists():
    try:
        seen = set(json.load(open(seen_file)).get("leads", []))
    except:
        pass

# Check recruiting forms (fast)
count = 0
for form_id in cfg.get("RECRUIT_FORM_IDS", [])[:3]:
    try:
        r = subprocess.run([
            "curl", "-s", "-m", "8",
            f"https://graph.facebook.com/v20.0/{form_id}/leads?access_token={token}&limit=20&fields=id,field_data"
        ], capture_output=True, text=True, timeout=10)
        
        data = json.loads(r.stdout)
        for lead in data.get("data", []):
            lid = lead.get("id")
            if lid not in seen:
                # Extract name, phone, email
                info = {}
                for field in lead.get("field_data", []):
                    name_key = field.get("name", "").lower()
                    val = (field.get("values") or [""])[0]
                    if "name" in name_key:
                        info["name"] = val
                    elif "phone" in name_key:
                        info["phone"] = val
                    elif "email" in name_key:
                        info["email"] = val
                
                if info.get("name"):
                    send_tg(info["name"], info.get("phone"), info.get("email"))
                    seen.add(lid)
                    count += 1
    except:
        pass

# Save seen
with open(seen_file, "w") as f:
    json.dump({"leads": list(seen)}, f)

if count > 0:
    with open(log_path, "a") as f:
        f.write(f"✓ {count} new leads\n")
