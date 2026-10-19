#!/usr/bin/env python3
"""
Indeed Login + Desktop Automation
Uses pyautogui for real mouse control on your Mac
"""
import pyautogui
import pyperclip
import time
import subprocess
import json
from pathlib import Path

# Disable failsafe
pyautogui.FAILSAFE = False

def get_tg_token():
    """Get Telegram token"""
    cfg = Path.home() / "epc-webhook" / "config.json"
    if cfg.exists():
        try:
            return json.load(open(cfg)).get("TG_BOT_TOKEN", "")
        except:
            pass
    return ""

def take_screenshot(name="screenshot"):
    """Take screenshot for debugging"""
    subprocess.run([
        "screencapture", "-x",
        f"/tmp/{name}.png"
    ])
    print(f"📸 {name}")

def type_text(text, delay=0.05):
    """Type text using pbcopy/paste (more reliable than direct typing)"""
    pyperclip.copy(text)
    pyautogui.hotkey('cmd', 'v')
    time.sleep(delay)

def click(x, y, delay=0.5):
    """Click at coordinates"""
    pyautogui.click(x, y)
    time.sleep(delay)

def login_indeed():
    """Log into Indeed and keep session alive"""
    print("[indeed] Opening Chrome...")
    
    # Open Chrome
    subprocess.run(["open", "-a", "Google Chrome"])
    time.sleep(3)
    
    # Navigate to Indeed
    pyautogui.hotkey('cmd', 't')
    time.sleep(1)
    
    type_text("https://employers.indeed.com/signin")
    pyautogui.press('return')
    time.sleep(4)
    
    print("[indeed] Entering credentials...")
    
    # Email field
    click(640, 300)  # Click email input (adjust if needed)
    time.sleep(0.5)
    type_text("travisdeanepc04@gmail.com")
    time.sleep(1)
    
    # Click Next
    click(640, 350)  # "Next" button (adjust)
    time.sleep(3)
    
    take_screenshot("after_next")
    
    # Password field
    click(640, 300)
    time.sleep(0.5)
    type_text("Travis2485")
    time.sleep(1)
    
    # Click Sign In
    click(640, 350)
    time.sleep(5)
    
    print("✅ Login complete. Chrome will stay open for 24/7 automation.")
    
    take_screenshot("logged_in")

def pull_indeed_applicants():
    """Click through Indeed applicants and extract info"""
    print("[indeed] Pulling applicants...")
    
    # Chrome should be open and logged in
    subprocess.run(["open", "-a", "Google Chrome"])
    time.sleep(2)
    
    # Navigate to candidates
    pyautogui.hotkey('cmd', 't')
    time.sleep(1)
    type_text("https://employers.indeed.com/candidates?id=6186a8e3e50c&tab=manage")
    pyautogui.press('return')
    time.sleep(5)
    
    take_screenshot("candidates_list")
    
    # JavaScript extraction
    print("[indeed] Extracting candidate info from page...")
    
    # Use AppleScript to run JS in Chrome
    script = '''
    tell application "Google Chrome"
        execute javascript "
        let rows = document.querySelectorAll('[data-testid=\"candidate-row\"]');
        let applicants = [];
        rows.forEach(row => {
            let text = row.innerText;
            let name = (text.split('\\n')[0] || '').trim();
            let email = (text.match(/[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}/i) || [''])[0];
            let phone = (text.match(/\\(?\\d{3}\\)?[\\s.-]?\\d{3}[\\s.-]?\\d{4}/) || [''])[0];
            if (name && (email || phone)) {
                applicants.push({name, email, phone});
            }
        });
        JSON.stringify(applicants);
        " in front window
    end tell
    '''
    
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        try:
            applicants = json.loads(result.stdout)
            print(f"✅ Found {len(applicants)} applicants")
            
            # Post to Telegram
            token = get_tg_token()
            if token:
                for app in applicants[:5]:  # Limit to 5
                    name = app.get("name", "Unknown")
                    email = app.get("email", "")
                    phone = app.get("phone", "")
                    
                    msg = f"🎯 **INDEED APPLICANT**\n`{name}`"
                    if email:
                        msg += f"\n📧 {email}"
                    if phone:
                        msg += f"\n📞 {phone}"
                    
                    cmd = [
                        "curl", "-s", "-X", "POST",
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        "-d", "chat_id=-5306696575",
                        "-d", f"text={msg}",
                        "-d", "parse_mode=Markdown"
                    ]
                    subprocess.run(cmd)
                    print(f"✅ Posted: {name}")
        except:
            print("❌ Parse error")
    else:
        print("❌ JS extraction failed")
    
    take_screenshot("final")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        login_indeed()
    else:
        pull_indeed_applicants()
