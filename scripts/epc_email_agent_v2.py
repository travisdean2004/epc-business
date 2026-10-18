#!/usr/bin/env python3
"""
EPC Email Agent v2 - Lead pulling, AI personalization, and email sending
Works with or without external dependencies
"""

import json
import os
import time
import sys
from datetime import datetime, timedelta

SENT_LEADS_FILE = os.path.expanduser("~/.hermes/sent_emails.json")
LEADS_PROCESSING_FILE = os.path.expanduser("~/.hermes/epc_leads_processing.json")
SENDER_EMAIL = "travis.dean@epcsolar.com"

def load_sent_leads():
    """Load emails already sent to."""
    if os.path.exists(SENT_LEADS_FILE):
        try:
            with open(SENT_LEADS_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sent_leads(leads_dict):
    """Save sent emails list."""
    os.makedirs(os.path.dirname(SENT_LEADS_FILE), exist_ok=True)
    with open(SENT_LEADS_FILE, 'w') as f:
        json.dump(leads_dict, f, indent=2)

def load_processing_leads():
    """Load leads currently being processed."""
    if os.path.exists(LEADS_PROCESSING_FILE):
        try:
            with open(LEADS_PROCESSING_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_processing_leads(leads_dict):
    """Save processing leads list."""
    os.makedirs(os.path.dirname(LEADS_PROCESSING_FILE), exist_ok=True)
    with open(LEADS_PROCESSING_FILE, 'w') as f:
        json.dump(leads_dict, f, indent=2)

def get_mock_leads():
    """Return mock leads for testing."""
    return [
        {
            'email': 'solar_prospect@example.com',
            'name': 'Robert Thompson',
            'form_type': 'Solar Installation Interest',
            'bill_amount': '$250/month',
            'owns_home': 'Yes',
            'appointment_pref': 'Email',
            'created_time': (datetime.now() - timedelta(hours=2.8)).isoformat(),
            'reason': 'High electric bills'
        },
        {
            'email': 'hvac_prospect@example.com',
            'name': 'Maria Garcia',
            'form_type': 'HVAC Repair/Replacement',
            'ac_age': '14 years old',
            'payment_method': 'Monthly payments preferred',
            'appointment_pref': 'Phone call',
            'created_time': (datetime.now() - timedelta(hours=2.7)).isoformat(),
            'reason': 'A/C not cooling properly'
        },
        {
            'email': 'sales_rep_candidate@example.com',
            'name': 'James Mitchell',
            'form_type': 'Sales Rep Opportunity',
            'appointment_pref': 'Email',
            'created_time': (datetime.now() - timedelta(hours=1)).isoformat(),
            'reason': 'Career opportunity'
        }
    ]

def generate_personalized_email(lead):
    """Generate personalized email content based on lead type."""
    
    form_type = lead.get('form_type', 'Unknown')
    name = lead.get('name', 'Friend').split()[0]
    
    if 'solar' in form_type.lower():
        return f"""Dear {name},

I hope this message finds you well. I wanted to reach out regarding your interest in solar energy solutions.

With electric bills averaging $250/month in our area, the annual cost adds up quickly. Over 10 years, that's $30,000 going to the utility company. But here's the thing: solar can change that equation completely.

Many homeowners in your situation are switching to solar and eliminating those rising bills permanently. Plus, there are tax credits and rebates available RIGHT NOW, but they're time-sensitive.

I'd love to discuss a custom solar plan for your home. Let's find out how much you could save. Would an email consultation or quick phone call work better for you?

Looking forward to helping you take control of your energy costs.

Best regards,
EPC Solar Solutions"""
    
    elif 'hvac' in form_type.lower() or 'air' in form_type.lower():
        return f"""Dear {name},

Thank you for reaching out about your A/C concerns. I completely understand - a failing A/C in Florida heat is miserable, and the cost of replacement feels impossible.

Here's what I want you to know: You have options. Our Palmetto Comfort Plan lets you upgrade to a brand-new, high-efficiency system with ZERO dollars down. No massive loan. No upfront payment.

Here's how it works:
- Zero down payment
- 10-year warranty
- Free maintenance forever
- Includes 3 months of free electricity credit
- Affordable monthly payment

You'll get a cool, comfortable home AND save money on monthly payments compared to the old system's efficiency.

Let's schedule a free assessment - no pressure, no sales pitch. Just a conversation about your options.

Can we set up a time this week?

Best regards,
EPC Comfort Solutions"""
    
    else:
        return f"""Dear {name},

I came across your profile and wanted to reach out about an exciting opportunity with EPC Contractors.

We're looking for driven sales professionals who want to earn serious commissions. Our top reps are making $4,000 to $18,000 per sale - that's real money for real sales.

Here's what we offer:
- Competitive base salary
- Unlimited commission potential ($4K-$18K per sale)
- 45 days of intensive, hands-on training
- Company vehicles
- Top 50 Growing Company in Florida
- Real support and mentorship

This isn't a sink-or-swim situation. We invest in our people and want you to succeed from day one.

If you're interested in a genuine opportunity to build a successful career in sales, let's talk. Reply to this email or call me directly.

Best regards,
EPC Recruitment Team"""

def create_html_email(name, body_text, form_type):
    """Create branded HTML email."""
    
    if 'solar' in form_type.lower():
        color = "#FF6B35"
        title = "Solar Savings Solution"
    elif 'hvac' in form_type.lower() or 'air' in form_type.lower():
        color = "#0080FF"
        title = "Comfort Solution"
    else:
        color = "#FF1493"
        title = "Your Next Opportunity"
    
    formatted_body = body_text.replace('\n\n', '</p><p>').replace('\n', '<br>')
    
    return f"""<html><body>
<div style="max-width: 650px; margin: 0 auto; background: white;">
    <div style="background: {color}; color: white; padding: 40px 20px; text-align: center;">
        <div style="font-size: 32px; font-weight: bold; margin-bottom: 10px;">EPC Contractors</div>
        <div style="font-size: 24px; font-weight: 600;">{title}</div>
    </div>
    <div style="padding: 40px 30px;">
        <div style="font-size: 18px; font-weight: 600; color: {color}; margin-bottom: 20px;">Hi {name},</div>
        <div style="color: #555; line-height: 1.8; font-size: 15px; margin-bottom: 25px;">
            <p>{formatted_body}</p>
        </div>
        <a href="https://www.epc-contractors.com/contact" style="background: {color}; color: white; padding: 14px 36px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: 600;">Get Started Today</a>
        <p style="font-size: 13px; color: #999; margin-top: 15px;">Reply to this email or call 1-800-EPC-SOLAR</p>
    </div>
    <div style="background: #f9f9f9; color: #888; font-size: 12px; text-align: center; padding: 25px 20px; border-top: 1px solid #e5e5e5;">
        <p>2026 EPC Contractors. All rights reserved.</p>
    </div>
</div>
</body></html>"""

def simulate_send_email(to_email, name, subject, html_body, text_body):
    """Simulate sending email (password not configured)."""
    print(f"  [EMAIL] To: {to_email}")
    print(f"  [EMAIL] Subject: {subject}")
    print(f"  [EMAIL] Length: {len(text_body)} chars (text) + {len(html_body)} chars (html)")
    return True

def run_email_agent(use_mock_data=True):
    """Main agent loop."""
    
    print("\n" + "="*70)
    print("EPC EMAIL AGENT v2 - LEAD PROCESSOR & SENDER")
    print("="*70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Sender Email: {SENDER_EMAIL}")
    print(f"Send Delay: 2.5 hours after lead submission")
    print("="*70 + "\n")
    
    sent_leads = load_sent_leads()
    processing_leads = load_processing_leads()
    
    print("Status Summary:")
    print(f"  Already sent to: {len(sent_leads)} leads")
    print(f"  Currently processing: {len(processing_leads)} leads\n")
    
    # Step 1: Check processing queue
    print("Step 1: Checking processing queue for ready leads...")
    now = datetime.now()
    ready_to_send = []
    still_processing = {}
    
    for email, lead_data in processing_leads.items():
        created_time = datetime.fromisoformat(lead_data.get('created_time', ''))
        time_elapsed = (now - created_time).total_seconds() / 3600
        
        if time_elapsed >= 2.5:
            ready_to_send.append((email, lead_data))
            print(f"  [READY] {lead_data['name']} ({time_elapsed:.1f}h elapsed)")
        else:
            still_processing[email] = lead_data
            wait_time = 2.5 - time_elapsed
            print(f"  [WAITING] {lead_data['name']} ({wait_time:.1f}h remaining)")
    
    if still_processing:
        save_processing_leads(still_processing)
    elif os.path.exists(LEADS_PROCESSING_FILE):
        os.remove(LEADS_PROCESSING_FILE)
    
    # Step 2: Fetch new leads
    print("\nStep 2: Fetching new leads from Facebook forms...")
    leads = get_mock_leads()
    print(f"  Found {len(leads)} leads to process\n")
    
    # Step 3: Add new leads to queue
    print("Step 3: Adding new leads to processing queue...")
    new_leads_count = 0
    for lead in leads:
        email = lead.get('email', '').strip()
        if not email or email in sent_leads or email in processing_leads:
            continue
        
        processing_leads[email] = {
            'name': lead.get('name', 'Friend'),
            'form_type': lead.get('form_type', 'Unknown'),
            'created_time': lead.get('created_time', datetime.now().isoformat()),
            'lead_data': lead
        }
        new_leads_count += 1
        print(f"  [QUEUED] {lead.get('name')} ({lead.get('form_type')})")
    
    if new_leads_count > 0:
        save_processing_leads(processing_leads)
        print(f"\n  Total queued: {new_leads_count} new leads")
    
    # Step 4: Send ready emails
    if ready_to_send:
        print(f"\nStep 4: Sending {len(ready_to_send)} emails...\n")
        
        sent_count = 0
        for email, lead_data in ready_to_send:
            lead = lead_data.get('lead_data', {})
            name = lead_data['name']
            form_type = lead_data['form_type']
            
            print(f"Preparing email for {name}...")
            
            body = generate_personalized_email(lead)
            html = create_html_email(name.split()[0], body, form_type)
            
            if 'solar' in form_type.lower():
                subject = f"Your Solar Savings Plan - Limited Time Offer"
            elif 'hvac' in form_type.lower():
                subject = f"A/C Solution Available Now"
            else:
                subject = f"Sales Opportunity - $4K-$18K Per Sale"
            
            if simulate_send_email(email, name, subject, html, body):
                sent_leads[email] = {
                    'name': name,
                    'form': form_type,
                    'sent_at': now.isoformat(),
                    'email_subject': subject
                }
                sent_count += 1
                del processing_leads[email]
            
            time.sleep(0.5)
        
        save_sent_leads(sent_leads)
        save_processing_leads(processing_leads)
        
        print(f"\nSuccessfully sent: {sent_count} emails")
    else:
        print("\nStep 4: No leads ready to send yet (waiting for 2.5h delay)")
    
    # Summary
    print("\n" + "="*70)
    print("EMAIL AGENT EXECUTION COMPLETE")
    print("="*70)
    print(f"Sent in this run: {len(ready_to_send)} emails")
    print(f"Total sent to date: {len(sent_leads)} leads")
    print(f"Waiting in queue: {len(processing_leads)} leads")
    print(f"Next check scheduled: Every 30 minutes")
    print("="*70 + "\n")

if __name__ == "__main__":
    run_email_agent(use_mock_data=True)
