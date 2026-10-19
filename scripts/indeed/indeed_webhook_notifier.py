#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Indeed employer account: travisdeanepc04@gmail.com
# Using cookie-based approach from Vlad-1618M/indeed_scraper
# Cookies saved to ~/.hermes/indeed_cookies.pkl after first login

SEEN_FILE = Path.home() / ".hermes" / "epc_indeed_seen_applicants.json"
TG_TOKEN = "YOUR_BOT_TOKEN"
TG_CHAT = "-5306696575"  # NEW HIRES

def load_seen():
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {}

def save_seen(data):
    SEEN_FILE.write_text(json.dumps(data))

def scrape_indeed():
    # Run the Vlad scraper with cookie persistence
    result = subprocess.run(
        ["python3", "scripts/indeed/scraper_src/main.py", 
         "--board", "indeed", "--use-cookies"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    return []

def post_to_telegram(name, phone, email, position, resume_summary):
    msg = f"🎯 **INDEED APPLICANT**\n"
    msg += f"**{name}**\n"
    msg += f"📞 {phone}\n"
    msg += f"📧 {email}\n"
    msg += f"💼 {position}\n"
    msg += f"📝 Resume: {resume_summary}\n"
    
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        "-d", f"chat_id={TG_CHAT}",
        "-d", f"text={msg}",
        "-d", "parse_mode=HTML"
    ]
    subprocess.run(cmd, capture_output=True)

def main():
    seen = load_seen()
    applicants = scrape_indeed()
    
    new_count = 0
    for app in applicants:
        key = f"{app['name']}|{app['email']}"
        if key not in seen:
            post_to_telegram(
                app.get("name"),
                app.get("phone"),
                app.get("email"),
                app.get("position"),
                app.get("resume_summary", "No summary")
            )
            seen[key] = datetime.now().isoformat()
            new_count += 1
    
    save_seen(seen)
    print(f"✅ Posted {new_count} new Indeed applicants")

if __name__ == "__main__":
    main()
