#!/usr/bin/env python3
"""
Indeed Retrieve Candidates API Poller (Oct 16 2026)
Pulls new applicants every 5 minutes via official Indeed API
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import urllib.request
import urllib.parse
import time

STATE_FILE = Path.home() / ".hermes" / "indeed_api_state.json"
CONFIG_FILE = Path.home() / "epc-webhook" / "config.json"

# Load config
cfg = json.load(open(CONFIG_FILE))
TG_BOT_TOKEN = cfg.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = "-5306696575"
EMPLOYER_ID = "6186a8e3e50c"

# Indeed API credentials (you'll need to add these to config)
INDEED_CLIENT_ID = cfg.get("INDEED_CLIENT_ID", "")
INDEED_CLIENT_SECRET = cfg.get("INDEED_CLIENT_SECRET", "")
INDEED_ACCESS_TOKEN = cfg.get("INDEED_ACCESS_TOKEN", "")

def send_to_tg(name, email, phone):
    """Post applicant to Telegram"""
    msg = f"👔 <b>NEW INDEED APPLICANT</b>\n"
    msg += f"<b>{name}</b>\n"
    if email:
        msg += f"📧 {email}\n"
    if phone:
        msg += f"📞 <code>{phone}</code>\n"
    msg += f"📲 <b>Call within 5 minutes!</b>"
    
    try:
        cmd = [
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            "-d", f"chat_id={TG_CHAT_ID}",
            "-d", f"text={msg}",
            "-d", "parse_mode=HTML"
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=8, text=True)
        return '"ok":true' in result.stdout
    except:
        return False

def get_candidates():
    """Fetch candidates from Indeed API"""
    if not INDEED_ACCESS_TOKEN:
        print("[indeed-api] No access token — cannot fetch candidates")
        return []
    
    try:
        url = f"https://apis.indeed.com/graphql"
        
        query = {
            "query": """
            query {
              employer(id: "%s") {
                candidates(first: 50, sortBy: MOST_RECENT) {
                  edges {
                    node {
                      id
                      name
                      email
                      phoneNumber
                      applications {
                        job {
                          title
                        }
                        appliedAt
                      }
                    }
                  }
                  pageInfo {
                    hasNextPage
                  }
                }
              }
            }
            """ % EMPLOYER_ID
        }
        
        headers = {
            "Authorization": f"Bearer {INDEED_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(query).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            
            candidates = []
            if 'data' in result and 'employer' in result['data']:
                for edge in result['data']['employer']['candidates']['edges']:
                    node = edge['node']
                    candidates.append({
                        'id': node['id'],
                        'name': node['name'],
                        'email': node['email'],
                        'phone': node['phoneNumber'],
                        'job': node['applications'][0]['job']['title'] if node['applications'] else 'Position',
                        'applied_at': node['applications'][0]['appliedAt'] if node['applications'] else datetime.now().isoformat()
                    })
            
            return candidates
    except Exception as e:
        print(f"[indeed-api] Error fetching candidates: {e}")
        return []

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def main():
    print(f"[indeed-api] Poll started at {datetime.now()}")
    
    if not INDEED_ACCESS_TOKEN:
        print("[indeed-api] ❌ No access token configured")
        print("[indeed-api] Need: INDEED_CLIENT_ID, INDEED_CLIENT_SECRET in config.json")
        return
    
    state = load_state()
    candidates = get_candidates()
    
    print(f"[indeed-api] Fetched {len(candidates)} candidates")
    
    new_count = 0
    for cand in candidates:
        cand_key = cand['id']
        
        if cand_key in state:
            continue
        
        # Skip old applicants (>5 days)
        try:
            applied = datetime.fromisoformat(cand['applied_at'].replace('Z', '+00:00'))
            if applied < datetime.now(applied.tzinfo) - timedelta(days=5):
                print(f"[indeed-api] Skipped {cand['name']} (older than 5 days)")
                state[cand_key] = datetime.now().isoformat()
                continue
        except:
            pass
        
        # Post to Telegram
        if send_to_tg(cand['name'], cand['email'], cand['phone']):
            print(f"✅ Posted: {cand['name']}")
            state[cand_key] = datetime.now().isoformat()
            new_count += 1
            time.sleep(0.5)
        else:
            print(f"❌ Failed to post: {cand['name']}")
    
    save_state(state)
    print(f"[indeed-api] Complete — {new_count} new applicants\n")

if __name__ == "__main__":
    main()
