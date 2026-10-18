#!/usr/bin/env python3
"""
Indeed Employers Dashboard Scraper with Chrome DevTools CDP
Monitors "Home Energy Consultant" job postings for new applicants
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

# Configuration
HERMES_HOME = Path.home() / ".hermes"
SEEN_FILE = HERMES_HOME / "epc_indeed_seen_applicants.txt"
TELEGRAM_CHAT_ID = -5306696575
LOG_FILE = HERMES_HOME / "epc_indeed_scraper.log"
CDP_HOST = "localhost"
CDP_PORT = 9222
INDEED_URL = "https://employers.indeed.com/jobs"
JOB_TITLE = "Home Energy Consultant"

def read_telegram_token():
    """Read Telegram token from .env file"""
    env_file = HERMES_HOME / ".env"
    if not env_file.exists():
        return None
    
    try:
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN=') and '***' not in line:
                    token = line.split('=', 1)[1].strip()
                    token = token.strip('"\'')
                    if token and '***' not in token[:10]:
                        return token
    except Exception:
        pass
    
    return os.getenv('TELEGRAM_BOT_TOKEN')

TELEGRAM_BOT_TOKEN = read_telegram_token()

def log_message(msg):
    """Log a message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_msg + "\n")
    except Exception:
        pass

def load_seen_applicants():
    """Load seen applicant IDs"""
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE, 'r') as f:
                return set(line.strip() for line in f if line.strip())
        except Exception:
            pass
    return set()

def save_seen_applicant(app_id):
    """Save an applicant ID as seen"""
    if app_id:
        try:
            with open(SEEN_FILE, 'a') as f:
                f.write(f"{app_id}\n")
        except Exception:
            pass

def send_telegram_message(text):
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN:
        log_message("Warning: No Telegram token available")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                log_message(f"✓ Telegram message sent")
                return True
    except urllib.error.URLError as e:
        log_message(f"✗ Telegram send failed: {e}")
    except Exception as e:
        log_message(f"✗ Error sending Telegram message: {e}")
    
    return False

def format_applicant_message(name, email, phone, resume_summary=""):
    """Format applicant for Telegram"""
    msg = f"👔 <b>NEW INDEED APPLICANT — [INDEED]</b>\n"
    msg += f"<b>Name:</b> {name}\n"
    msg += f"<b>Email:</b> {email}\n"
    msg += f"<b>Phone:</b> {phone}\n"
    
    if resume_summary:
        summary = resume_summary[:150].replace('\n', ' ')
        msg += f"\n<b>Resume:</b> {summary}..."
    
    return msg

def check_chrome_connection():
    """Check if Chrome DevTools Protocol is available"""
    try:
        with urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/version", timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read())
                version = data.get('Browser', 'Unknown')
                log_message(f"✓ Connected to Chrome: {version}")
                return True
    except Exception as e:
        log_message(f"✗ Cannot connect to Chrome DevTools Protocol: {e}")
        log_message("   Make sure Chrome is running with: chrome --remote-debugging-port=9222")
    
    return False

def get_open_tabs():
    """Get list of open tabs from Chrome"""
    try:
        with urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/list", timeout=5) as resp:
            tabs = json.loads(resp.read())
            return tabs
    except Exception as e:
        log_message(f"Error getting tabs: {e}")
    return []

def extract_applicants_from_page(html_content):
    """Extract applicant information from page HTML"""
    applicants = []
    
    try:
        # Look for applicant patterns in HTML
        # These patterns are typical for Indeed employer dashboard
        
        # Pattern 1: Look for applicant names in divs/spans
        name_pattern = r'<(?:span|div)[^>]*class="[^"]*applicant-name[^"]*"[^>]*>([^<]+)</(?:span|div)>'
        names = re.findall(name_pattern, html_content, re.IGNORECASE)
        
        # Pattern 2: Look for email addresses
        email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        emails = re.findall(email_pattern, html_content)
        
        # Pattern 3: Look for phone numbers
        phone_pattern = r'(\+?1?\s?(?:\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}|\d{10}))'
        phones = re.findall(phone_pattern, html_content)
        
        log_message(f"Found {len(names)} names, {len(emails)} emails, {len(phones)} phones in HTML")
        
    except Exception as e:
        log_message(f"Error extracting applicants: {e}")
    
    return applicants

def main():
    log_message("=== Indeed Applicants Scraper Started ===")
    
    # Check Chrome connection
    if not check_chrome_connection():
        log_message("Cannot proceed without Chrome DevTools Protocol")
        return 1
    
    # Load seen applicants
    seen = load_seen_applicants()
    log_message(f"Loaded {len(seen)} previously seen applicants")
    
    # Get current tabs
    log_message("Checking open tabs...")
    tabs = get_open_tabs()
    indeed_tabs = [t for t in tabs if 'indeed' in t.get('url', '').lower()]
    log_message(f"Found {len(indeed_tabs)} Indeed-related tabs")
    
    applicants_found = 0
    new_applicants = 0
    
    for tab in indeed_tabs[:5]:
        url = tab.get('url', 'N/A')
        title = tab.get('title', 'Unknown')
        
        if 'employers.indeed.com' in url:
            log_message(f"Processing tab: {title[:50]}")
            log_message(f"  URL: {url[:80]}")
    
    # Try to fetch Indeed page directly as fallback
    try:
        log_message(f"Attempting to fetch {INDEED_URL}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        req = urllib.request.Request(INDEED_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                html = resp.read().decode('utf-8', errors='ignore')
                log_message(f"Successfully fetched {len(html)} bytes from Indeed")
                
                # Extract applicants
                applicants = extract_applicants_from_page(html)
                applicants_found = len(applicants)
                log_message(f"Extracted {applicants_found} applicants from page")
                
                # Process each applicant
                for applicant in applicants:
                    app_id = applicant.get('id')
                    
                    if app_id not in seen:
                        new_applicants += 1
                        name = applicant.get('name', 'Unknown')
                        email = applicant.get('email', 'N/A')
                        phone = applicant.get('phone', 'N/A')
                        resume = applicant.get('resume_summary', '')
                        
                        message = format_applicant_message(name, email, phone, resume)
                        
                        if send_telegram_message(message):
                            save_seen_applicant(app_id)
                            log_message(f"✓ Posted new applicant: {name}")
                        else:
                            log_message(f"✗ Failed to post applicant: {name}")
                        
                        time.sleep(0.5)  # Rate limiting
    except urllib.error.HTTPError as e:
        log_message(f"HTTP Error fetching Indeed page: {e.code}")
    except Exception as e:
        log_message(f"Error fetching Indeed page: {e}")
    
    log_message(f"Scraper check complete. Found {applicants_found} applicants, {new_applicants} new.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
