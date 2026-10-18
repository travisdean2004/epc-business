#!/usr/bin/env python3
"""
Indeed candidate checker — opens the Indeed employer candidates page in Chrome,
extracts candidate data via JS, sends NEW candidates to EPC NEW HIRES Telegram group.
Runs headlessly — Chrome must already be logged in.
"""
import subprocess, json, os, time, sys

SEEN_FILE = os.path.expanduser("~/.hermes/indeed_seen_candidates.txt")
CONFIG_FILE = os.path.expanduser("~/epc-webhook/config.json")
CHAT_ID = "-5306696575"

def get_token():
    cfg = json.load(open(CONFIG_FILE))
    return cfg.get("TG_BOT_TOKEN", "")

def send_tg(token, msg):
    payload = json.dumps({"chat_id": CHAT_ID, "text": msg})
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{token}/sendMessage",
        "-H", "Content-Type: application/json",
        "-d", payload
    ], capture_output=True)

def run_js(js):
    """Run JavaScript in Chrome's active tab and return result."""
    escaped = js.replace('"', '\\"').replace('\n', ' ')
    script = f'''
    tell application "Google Chrome"
        tell active tab of window 1
            execute javascript "{escaped}"
        end tell
    end tell
    '''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip()

def open_indeed_tab():
    script = '''
    tell application "Google Chrome"
        tell window 1
            set newTab to make new tab
            set URL of newTab to "https://employers.indeed.com/candidates?statusName=All&tab=manage&id=0"
            set active tab index to (count of tabs)
        end tell
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)
    time.sleep(9)  # wait for page load

def close_active_tab():
    script = 'tell application "Google Chrome" to close active tab of window 1'
    subprocess.run(["osascript", "-e", script], capture_output=True)

def get_candidates():
    """Extract candidate cards from the page via JS."""
    js = """
    (function() {
        var results = [];
        var cards = document.querySelectorAll('[data-testid="candidate-card"], .css-candidate-card, [class*="CandidateCard"]');
        if (cards.length === 0) {
            // fallback: grab all candidate name elements
            cards = document.querySelectorAll('h2[class*="name"], [data-testid="candidate-name"]');
        }
        // Try generic approach: find candidate name + location + status
        var rows = document.querySelectorAll('[class*="candidateCard"], [class*="candidate-card"], [class*="CandidateListItem"]');
        if (rows.length === 0) {
            // broader fallback
            rows = document.querySelectorAll('li[class*="css-"], div[class*="Candidate"]');
        }
        rows.forEach(function(row) {
            var name = row.querySelector('a[href*="resume"], [class*="name"], h2, h3');
            var loc = row.querySelector('[class*="location"], [class*="Location"]');
            var status = row.querySelector('[class*="status"], [class*="Status"], [class*="applied"]');
            var title = row.querySelector('[class*="title"], [class*="Title"]');
            if (name && name.textContent.trim()) {
                results.push({
                    name: name.textContent.trim(),
                    location: loc ? loc.textContent.trim() : '',
                    status: status ? status.textContent.trim() : '',
                    title: title ? title.textContent.trim() : ''
                });
            }
        });
        // absolute fallback — scrape all visible text blocks that look like candidates
        if (results.length === 0) {
            var nameEls = document.querySelectorAll('[class*="applicant"] a, [class*="candidate"] a');
            nameEls.forEach(function(el) {
                var t = el.textContent.trim();
                if (t.length > 2 && t.length < 60) results.push({name: t, location:'', status:'', title:''});
            });
        }
        return JSON.stringify(results);
    })()
    """
    raw = run_js(js)
    try:
        return json.loads(raw)
    except Exception:
        return []

def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    return set(l.strip() for l in open(SEEN_FILE).readlines() if l.strip())

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        f.write("\n".join(seen))

def main():
    token = get_token()
    if not token:
        sys.exit(0)

    seen = load_seen()
    open_indeed_tab()

    candidates = get_candidates()
    close_active_tab()

    if not candidates:
        sys.exit(0)

    new_ones = []
    for c in candidates:
        key = c["name"].strip().lower().replace(" ", "_")
        if key and key not in seen:
            new_ones.append(c)
            seen.add(key)

    if new_ones:
        save_seen(seen)
        lines = ["🧑‍💼 NEW INDEED APPLICANT(S)\n"]
        for i, c in enumerate(new_ones, 1):
            lines.append(f"{i}. {c['name']}" + (f" — {c['location']}" if c['location'] else ""))
            if c['title']:
                lines.append(f"   💼 {c['title']}")
            if c['status']:
                lines.append(f"   📅 {c['status']}")
        lines.append("\n🌐 employers.indeed.com/candidates\n📲 Text within 5 min!")
        send_tg(token, "\n".join(lines))

if __name__ == "__main__":
    main()
