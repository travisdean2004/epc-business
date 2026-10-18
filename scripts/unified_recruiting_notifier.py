#!/usr/bin/env python3
"""
Unified Recruiting Lead Notifier
Pulls leads from: Facebook Ads + Indeed + Website Queue
Posts formatted alerts to: EPC New Hires Telegram Chat (-5306696575)

Runs every 5 minutes via cron.
"""
import os, sys, json, subprocess, re
from datetime import datetime, timezone
from pathlib import Path

# Config
SEEN_FB_FILE = os.path.expanduser('~/.hermes/epc_recruiting_seen_leads.txt')
SEEN_INDEED_FILE = os.path.expanduser('~/.hermes/indeed_seen_candidates.txt')
NEW_HIRES_CHAT = '-5306696575'
CONFIG_FILE = os.path.expanduser('~/epc-webhook/config.json')
QUEUE_FILE = os.path.expanduser('~/.hermes/recruit_text_queue.json')

def get_bot_token():
    """Get real Telegram bot token from hermes venv."""
    try:
        result = subprocess.run(
            ['/Users/tdizzlewizzle/.hermes/hermes-agent/venv/bin/python', '-c',
             "from hermes_cli.config import load_env; print(load_env().get('TELEGRAM_BOT_TOKEN',''))"],
            capture_output=True, text=True, timeout=5
        )
        token = result.stdout.strip()
        if token and not token.startswith('Error'):
            return token
    except:
        pass
    
    # Fallback to config.json
    try:
        cfg = json.load(open(CONFIG_FILE))
        return cfg.get('TG_BOT_TOKEN', '')
    except:
        return ''

def send_tg(text):
    """Send message to NEW HIRES chat via Telegram."""
    token = get_bot_token()
    if not token:
        print('[warn] no telegram token available', file=sys.stderr)
        return False
    
    payload = json.dumps({'chat_id': NEW_HIRES_CHAT, 'text': text})
    result = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         f'https://api.telegram.org/bot{token}/sendMessage',
         '-H', 'Content-Type: application/json',
         '-d', payload],
        capture_output=True, text=True, timeout=10
    )
    
    try:
        resp = json.loads(result.stdout)
        return resp.get('ok', False)
    except:
        return False

def get_fb_config():
    """Load Facebook form IDs and token from config."""
    try:
        cfg = json.load(open(CONFIG_FILE))
        return {
            'forms': cfg.get('RECRUIT_FORM_IDS', []),
            'token': cfg.get('PAGE_ACCESS_TOKEN') or cfg.get('SYSTEM_TOKEN'),
            'page_id': cfg.get('PAGE_ID', '')
        }
    except:
        return {'forms': [], 'token': None, 'page_id': ''}

def get_fb_leads():
    """Fetch new leads from Facebook lead forms."""
    cfg = get_fb_config()
    if not cfg['token'] or not cfg['forms']:
        return []
    
    leads = []
    for form_id in cfg['forms']:
        try:
            result = subprocess.run(
                ['curl', '-s',
                 f"https://graph.facebook.com/v20.0/{form_id}/leads?fields=id,created_time,field_data&limit=50&access_token={cfg['token']}"],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(result.stdout)
            for lead in data.get('data', []):
                leads.append({
                    'source': 'facebook',
                    'id': lead.get('id'),
                    'created_at': lead.get('created_time'),
                    'fields': {f['name']: f.get('values', [None])[0] for f in lead.get('field_data', [])}
                })
        except Exception as e:
            print(f'[error] fb form {form_id}: {e}', file=sys.stderr)
    
    return leads

def get_indeed_leads():
    """Check for new Indeed applicants (from website scrape data)."""
    # This is a placeholder — Indeed applicants come from indeed_candidate_checker.py
    # which also posts to Telegram. We can sync via a shared file if needed.
    return []

def get_website_queue_leads():
    """Get leads from website form queue that haven't been posted yet."""
    if not os.path.exists(QUEUE_FILE):
        return []
    
    leads = []
    try:
        queue = json.load(open(QUEUE_FILE))
        for lead_id, lead in queue.items():
            if lead.get('posted_to_telegram'):
                continue
            leads.append({
                'source': 'website',
                'id': lead_id,
                'created_at': datetime.fromtimestamp(lead.get('queued_at', 0)).isoformat() + 'Z',
                'fields': {
                    'full_name': lead.get('name'),
                    'phone_number': lead.get('phone'),
                    'email': lead.get('email'),
                    'city': lead.get('city', ''),
                    'salesexperience': lead.get('experience', '')
                }
            })
    except:
        pass
    
    return leads

def format_lead_msg(lead):
    """Format lead into Telegram message."""
    fields = lead.get('fields', {})
    name = fields.get('full_name') or fields.get('name') or '?'
    phone = fields.get('phone_number') or fields.get('phone') or '?'
    city = fields.get('city') or fields.get('city_state') or ''
    exp = fields.get('salesexperience') or fields.get('sales_experience') or ''
    source = lead.get('source', '?').upper()
    
    # Clean phone
    phone_clean = re.sub(r'\D', '', phone) if phone != '?' else '?'
    if phone_clean and len(phone_clean) == 10:
        phone = f"+1{phone_clean}"
    elif phone_clean and len(phone_clean) == 11 and phone_clean[0] == '1':
        phone = f"+{phone_clean}"
    
    # Summary
    exp_short = 'Yes' if exp and exp.lower() not in ['no', 'none', ''] else 'No'
    
    msg = f"""🔔 NEW {source} APPLICANT

👤 {name}
📞 {phone}"""
    
    if city:
        msg += f"\n📍 {city}"
    
    msg += f"\n💼 Sales exp: {exp_short}"
    
    return msg

def mark_seen(lead):
    """Mark lead as seen so we don't duplicate."""
    source = lead.get('source')
    lead_id = lead.get('id')
    
    if source == 'facebook':
        # Write to seen file
        with open(SEEN_FB_FILE, 'a') as f:
            f.write(f"{lead_id}\n")
    elif source == 'website':
        # Mark in queue
        try:
            queue = json.load(open(QUEUE_FILE))
            if lead_id in queue:
                queue[lead_id]['posted_to_telegram'] = True
            json.dump(queue, open(QUEUE_FILE, 'w'), indent=2)
        except:
            pass

def get_seen_ids():
    """Load previously seen lead IDs."""
    seen = set()
    if os.path.exists(SEEN_FB_FILE):
        seen.update(line.strip() for line in open(SEEN_FB_FILE) if line.strip())
    if os.path.exists(SEEN_INDEED_FILE):
        seen.update(line.strip() for line in open(SEEN_INDEED_FILE) if line.strip())
    return seen

def main():
    seen = get_seen_ids()
    
    # Fetch all leads
    fb_leads = get_fb_leads()
    web_leads = get_website_queue_leads()
    
    all_leads = fb_leads + web_leads
    
    # Filter new
    new_leads = [l for l in all_leads if l.get('id') not in seen]
    
    if not new_leads:
        print('[info] no new leads', file=sys.stderr)
        return
    
    # Send each new lead
    for lead in new_leads:
        msg = format_lead_msg(lead)
        if send_tg(msg):
            mark_seen(lead)
            print(f'[sent] {lead.get("source")} lead: {lead.get("id")}')
        else:
            print(f'[error] failed to send {lead.get("source")} lead: {lead.get("id")}', file=sys.stderr)

if __name__ == '__main__':
    main()
