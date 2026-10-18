#!/usr/bin/env python3
"""Email automation agent - pulls leads, generates personalized emails, sends automatically."""

import json
import os
import smtplib
import requests
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from anthropic import Anthropic

# Configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "travis.dean@epcsolar.com"
SENDER_PASSWORD = "Travis2485"
SENT_LEADS_FILE = os.path.expanduser("~/epc/sent_emails.json")

# Facebook API config
FB_TOKEN = "EAAOXWs69AdsBSjfW9eiBTWF4sN0b18ZAJORvY9ZCnCGGDuQOz8FjUeAfnqzZBTVVk4pmcbenUj9Nr3HWnACDijZCMRfmITPt8NrkftWmDa6wZATbQvtXOQlRaOTR3zZAshZAzZAqt5NBi21m2avapLzj7PSHFIMFlfRyGHBSR5W4sfNcPD84oB5ozkHaASvtygZDZD"
AD_ACCOUNT_ID = 'act_20032154'

client = Anthropic()

def load_sent_leads():
    """Load emails already sent to."""
    if os.path.exists(SENT_LEADS_FILE):
        with open(SENT_LEADS_FILE) as f:
            return json.load(f)
    return {}

def save_sent_leads(leads_dict):
    """Save sent emails list."""
    os.makedirs(os.path.dirname(SENT_LEADS_FILE), exist_ok=True)
    with open(SENT_LEADS_FILE, 'w') as f:
        json.dump(leads_dict, f, indent=2)

def get_facebook_leads():
    """Fetch leads from Facebook lead forms."""
    leads = []
    
    # Get lead forms
    response = requests.get(
        f"https://graph.facebook.com/v18.0/{AD_ACCOUNT_ID}/leadgen_forms",
        params={'access_token': FB_TOKEN, 'fields': 'id,name'}
    )
    
    forms = response.json().get('data', [])
    
    for form in forms:
        form_id = form['id']
        
        # Get leads from this form
        response = requests.get(
            f"https://graph.facebook.com/v18.0/{form_id}/leads",
            params={'access_token': FB_TOKEN, 'fields': 'id,created_time,field_data'}
        )
        
        form_leads = response.json().get('data', [])
        
        for lead in form_leads:
            field_data = lead.get('field_data', [])
            
            # Parse form fields
            lead_info = {'form_type': form.get('name', 'Unknown')}
            
            for field in field_data:
                field_name = field.get('name', '').lower()
                field_value = field.get('value', '')
                
                if 'email' in field_name:
                    lead_info['email'] = field_value
                elif 'name' in field_name:
                    lead_info['name'] = field_value
                elif 'phone' in field_name:
                    lead_info['phone'] = field_value
                elif 'bill' in field_name or 'monthly' in field_name:
                    lead_info['bill_amount'] = field_value
                elif 'own' in field_name or 'home' in field_name:
                    lead_info['owns_home'] = field_value
                elif 'ac' in field_name or 'a/c' in field_name or 'age' in field_name:
                    lead_info['ac_age'] = field_value
                elif 'service' in field_name:
                    lead_info['last_service'] = field_value
                elif 'pay' in field_name or 'method' in field_name:
                    lead_info['payment_method'] = field_value
                elif 'appointment' in field_name:
                    lead_info['appointment_pref'] = field_value
            
            if 'email' in lead_info and lead_info['email']:
                leads.append(lead_info)
    
    return leads

def generate_personalized_email(lead):
    """Generate AI-personalized email using Claude."""
    
    form_type = lead.get('form_type', 'Unknown')
    name = lead.get('name', 'Friend').split()[0]  # First name only
    
    if 'Solar' in form_type:
        context = f"""Generate an URGENT, FEAR-BASED email for {name} about solar energy.

THEIR INFO:
- Monthly electric bill: {lead.get('bill_amount', 'Unknown')}
- Own home: {lead.get('owns_home', 'Unknown')}
- Wants: {lead.get('appointment_pref', 'Email')}

TONE: Fear + Urgency. Government blackouts COMING. Electric bills DOUBLING. This is NOT optional.

EMAIL RULES:
1. HOOK FIRST LINE: "Government blackouts are hitting Florida this winter. Your electric bill just doubled."
2. Personalize: Use {name}'s name, acknowledge their bill amount
3. Paint the PAIN: "Without solar, you're looking at {lead.get('bill_amount', '$400')} bills forever. That's {lead.get('bill_amount', '$400')} × 12 = $XXXX per year"
4. Solution: "Solar eliminates that. Permanently."
5. Urgency: "Limited spots for winter installations"
6. CTA: "Reply to this email or call now"

SHORT, scannable, 3-4 paragraphs max. Line breaks. Make them FEEL the fear."""
    
    elif 'HVAC' in form_type:
        context = f"""Generate a PAIN-FOCUSED email for {name} about HVAC/Palmetto Comfort Plan.

THEIR INFO:
- A/C age: {lead.get('ac_age', 'Unknown')}
- Payment method: {lead.get('payment_method', 'Unknown')}
- Wants: {lead.get('appointment_pref', 'Email')}

TONE: Empathy + Solution. "I know it's hot. I know $8,000 sucks. I have the answer."

EMAIL RULES:
1. HOOK FIRST LINE: "I know your A/C is {lead.get('ac_age', 'old')} and dying. $8,000 cash? Massive loan? No thanks."
2. Personalize: Use {name}'s name, acknowledge their A/C age and payment concerns
3. Paint the PAIN: "Summer in Florida with a broken A/C = miserable. But $8K upfront is impossible for most people."
4. SOLUTION - PALMETTO COMFORT PLAN: "$0 Down HVAC Lease. 10-year warranty. Free maintenance forever. No massive loan."
5. Benefits: "3 months free electric included. 10 years of free service/cleaning/tune-ups"
6. CTA: "Let's get you cool again without the financial pain"

SHORT, scannable, 3-4 paragraphs max. EMPATHY FIRST, THEN SOLUTION."""
    
    else:  # Sales Reps
        context = f"""Generate a recruiting email for {name} about sales rep opportunity.

TONE: Excitement + Opportunity. "You could be making $4K-$18K per sale by year-end."

EMAIL RULES:
1. HOOK: "Base pay + commission + 80% raise after 45-day training"
2. Personalize: Use {name}'s name
3. Show the upside: "$4,000 - $18,000 per sale. That's real money."
4. Culture: "We're Top 50 Growing Companies in Florida. Growth encouraged. Company vehicles."
5. Training: "45 days of intensive training, not sink-or-swim"
6. CTA: "Let's chat about your next opportunity"

SHORT, enthusiastic, 3-4 paragraphs."""
    
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": context}]
    )
    
    return response.content[0].text

def create_html_email(name, body_text, form_type):
    """Create branded HTML newsletter."""
    
    if 'Solar' in form_type:
        color = "#FF6B35"  # Orange/solar
        title = "Solar Savings Alert"
    elif 'HVAC' in form_type:
        color = "#0080FF"  # Blue/cooling
        title = "Comfort Solution"
    else:
        color = "#FF1493"  # Pink/recruiting
        title = "Your Next Move"
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; margin: 0; }}
        .container {{ max-width: 600px; margin: 20px auto; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, {color} 0%, {color}dd 100%); color: white; padding: 30px 20px; text-align: center; }}
        .logo {{ font-size: 28px; font-weight: bold; margin-bottom: 10px; }}
        .subtitle {{ font-size: 14px; opacity: 0.9; }}
        .content {{ padding: 30px 25px; }}
        .greeting {{ font-size: 18px; font-weight: 600; color: #333; margin-bottom: 15px; }}
        .body-text {{ color: #555; line-height: 1.6; font-size: 15px; margin-bottom: 20px; }}
        .cta {{ background: {color}; color: white; padding: 14px 28px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: 600; margin-top: 15px; }}
        .cta:hover {{ opacity: 0.9; }}
        .footer {{ background: #f9f9f9; color: #999; font-size: 12px; text-align: center; padding: 20px; border-top: 1px solid #eee; }}
        .footer a {{ color: #0080FF; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">EPC Contractors</div>
            <div class="subtitle">{title}</div>
        </div>
        <div class="content">
            <div class="greeting">Hi {name},</div>
            <div class="body-text">{body_text.replace(chr(10), '<br>')}</div>
            <a href="https://epc-contractors.org/" class="cta">Learn More</a>
        </div>
        <div class="footer">
            <p>© 2026 EPC Contractors. All rights reserved.<br>
            <a href="#">Unsubscribe</a> | <a href="#">Preferences</a></p>
        </div>
    </div>
</body>
</html>"""
    return html

def send_email(to_email, name, subject, html_body, text_body):
    """Send email via Gmail SMTP."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Reply-To'] = SENDER_EMAIL
        
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent to {to_email} ({name})")
        return True
    except Exception as e:
        print(f"❌ Email send failed for {to_email}: {str(e)}")
        return False

def run_email_agent():
    """Main loop - fetch leads, generate emails, send automatically."""
    
    print(f"\n{'='*60}")
    print(f"📧 EPC Email Agent Running")
    print(f"{'='*60}\n")
    
    sent_leads = load_sent_leads()
    print(f"Previously sent to: {len(sent_leads)} leads\n")
    
    # Get new leads
    print("🔍 Fetching leads from Facebook forms...")
    leads = get_facebook_leads()
    print(f"Found {len(leads)} total leads\n")
    
    new_count = 0
    for lead in leads:
        email = lead.get('email', '').strip()
        if not email or email in sent_leads:
            continue
        
        new_count += 1
        name = lead.get('name', 'Friend')
        form_type = lead.get('form_type', 'Unknown')
        
        print(f"📮 {name} ({form_type}) - {email}")
        
        # Generate personalized email
        body = generate_personalized_email(lead)
        
        # Create HTML version
        html = create_html_email(name.split()[0], body, form_type)
        
        # Send email
        subject = f"Special Offer for You - EPC {form_type}"
        if send_email(email, name, subject, html, body):
            sent_leads[email] = {
                'name': name,
                'form': form_type,
                'sent_at': datetime.now().isoformat()
            }
            save_sent_leads(sent_leads)
        
        # Brief delay between sends
        time.sleep(2)
    
    print(f"\n{'='*60}")
    print(f"✅ Email Agent Complete")
    print(f"   Sent {new_count} new emails")
    print(f"   Total sent so far: {len(sent_leads)}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_email_agent()
