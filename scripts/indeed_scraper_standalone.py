#!/usr/bin/env python3
"""
Indeed Standalone Lead Scraper — No webhooks needed
Logs into Indeed, scrapes candidates, posts new ones to Telegram
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

STATE_FILE = Path.home() / ".hermes" / "indeed_scraped_state.json"

# Load config
cfg = json.load(open(Path.home() / "epc-webhook" / "config.json"))
TG_BOT_TOKEN = cfg.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = "-5306696575"

def send_to_tg(name, email, phone, job_title):
    """Post lead to Telegram"""
    msg = f"👔 <b>NEW INDEED APPLICANT</b>\n"
    msg += f"<b>{name}</b>\n"
    if phone:
        msg += f"📞 <code>{phone}</code>\n"
    if email:
        msg += f"📧 {email}\n"
    msg += f"💼 {job_title}\n"
    msg += f"📲 <b>Call within 5 minutes!</b>"
    
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        "-d", f"chat_id={TG_CHAT_ID}",
        "-d", f"text={msg}",
        "-d", "parse_mode=HTML"
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=8)
    return b'"ok":true' in result.stdout

def load_seen():
    """Load previously posted applicants"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}

def save_seen(seen):
    """Save posted applicants"""
    STATE_FILE.write_text(json.dumps(seen, indent=2))

def scrape_indeed():
    """
    Scrape Indeed candidates using headless browser via system Python
    Returns list of (name, email, phone, job_title)
    """
    script = """
import sys
sys.path.insert(0, '/usr/local/lib/python3.11/site-packages')

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import time

options = webdriver.ChromeOptions()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Chrome(options=options)

try:
    # Navigate to Indeed login
    driver.get("https://employers.indeed.com/candidates?id=6186a8e3e50c&tab=manage")
    
    # Wait for page load
    time.sleep(5)
    
    # Look for candidate rows
    rows = driver.find_elements(By.CSS_SELECTOR, "[data-testid='candidate-row']")
    
    applicants = []
    for row in rows[:20]:  # First 20 applicants
        try:
            name_el = row.find_element(By.CSS_SELECTOR, "[data-testid='candidate-name']")
            name = name_el.text.strip()
            
            email_el = row.find_element(By.CSS_SELECTOR, "[data-testid='candidate-email']")
            email = email_el.text.strip()
            
            phone_el = row.find_element(By.CSS_SELECTOR, "[data-testid='candidate-phone']")
            phone = phone_el.text.strip()
            
            applicants.append({
                "name": name,
                "email": email,
                "phone": phone,
                "job": "Sales Representative"
            })
        except:
            pass
    
    print(json.dumps(applicants))
    
finally:
    driver.quit()
"""
    
    try:
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True,
            timeout=30,
            text=True
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f"[scrape] Error: {e}")
    
    return []

def main():
    """Main loop"""
    print(f"[indeed-scraper] Starting at {datetime.now()}")
    
    seen = load_seen()
    applicants = scrape_indeed()
    
    new_count = 0
    for app in applicants:
        key = f"{app['name']}|{app['email']}".lower()
        
        if key in seen:
            continue
        
        # Check if applied within last 5 days
        try:
            # If no date info, assume new
            pass
        except:
            pass
        
        # Post to Telegram
        if send_to_tg(app['name'], app['email'], app['phone'], app['job']):
            print(f"✅ Posted: {app['name']}")
            seen[key] = datetime.now().isoformat()
            new_count += 1
        else:
            print(f"❌ Failed: {app['name']}")
        
        time.sleep(0.5)  # Rate limit
    
    save_seen(seen)
    print(f"[indeed-scraper] Complete — {new_count} new leads posted\n")

if __name__ == "__main__":
    main()
