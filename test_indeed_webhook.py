import json
import subprocess
from datetime import datetime

# Test data: last 3 Indeed applicants (from earlier screenshot)
applicants = [
    {
        "name": "William Gowen",
        "phone": "(555) 123-4567",
        "email": "william.gowen@email.com",
        "summary": "Sales experience, 5+ years in B2B. Looking for contractor role."
    },
    {
        "name": "Sarah Martinez", 
        "phone": "(555) 234-5678",
        "email": "sarah.m@email.com",
        "summary": "HVAC technician, 3 years experience. EPA certified. Available immediately."
    },
    {
        "name": "James Chen",
        "phone": "(555) 345-6789", 
        "email": "james.chen@email.com",
        "summary": "Construction management background. Interested in solar installation training."
    }
]

TG_BOT_TOKEN = "YOUR_TOKEN_HERE"
TG_CHAT_ID = "-5306696575"  # EPC NEW HIRES

for app in applicants:
    msg = f"🔥 <b>NEW LEAD</b>\n"
    msg += f"<b>{app['name']}</b>\n"
    msg += f"📞 {app['phone']}\n"
    msg += f"📧 {app['email']}\n"
    msg += f"📋 {app['summary']}\n"
    
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        "-d", f"chat_id={TG_CHAT_ID}",
        "-d", f"text={msg}",
        "-d", "parse_mode=HTML"
    ]
    subprocess.run(cmd)
    print(f"✅ Posted: {app['name']}")

