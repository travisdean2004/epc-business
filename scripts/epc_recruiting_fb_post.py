#!/usr/bin/env python3
"""
EPC Recruiting Facebook Post — no_agent script.
Rotates through 4 post variations, tracks last posted via state file.
Posts Mon/Wed/Fri/Sun at 9am.
"""
import json, os, subprocess, sys
from datetime import datetime

CFG_PATH   = os.path.expanduser("~/epc-webhook/config.json")
STATE_FILE = os.path.expanduser("~/.hermes/epc_fb_post_state.json")
PAGE_ID    = "104084848517243"

cfg = json.load(open(CFG_PATH))
TOKEN = cfg.get("PAGE_ACCESS_TOKEN") or cfg.get("SYSTEM_TOKEN", "")

POSTS = [
    """🦩 WE ARE HIRING IN TAMPA BAY — RIGHT NOW.

Appointment Setters and Closers needed across Hillsborough, Pasco, Pinellas, and Hernando counties.

Setter (first 90 days): $4,000 - $8,000 per month
Closer (trained): $8,000 - $12,000+ per month

Full training. Team uniforms. Daily coaching. Real income.

No experience needed — just show up coachable and ready to work.

Group interviews every Tuesday and Thursday.
331 Scarlet Blvd, Oldsmar FL 34677

Apply in 60 seconds: epc-contractors.org/careers""",

    """💰 Our reps made $4,000 - $12,000+ last month in Tampa Bay solar sales.

EPC Contractors is hiring Appointment Setters and Closers right now.

We provide the leads. We provide the training. We provide the system.
You execute and get paid.

Recent grads, career changers, and motivated people who are tired of being underpaid — this is for you.

Interviews Tue and Thu — 331 Scarlet Blvd, Oldsmar FL 34677
Apply: epc-contractors.org/careers""",

    """🌞 Tampa Bay's solar market is BOOMING and EPC Contractors is growing fast.

We need Appointment Setters and Closers to join our in-house team immediately.

What we offer:
✅ $4,000 - $8,000/month as a Setter
✅ $8,000 - $12,000+/month as a Closer
✅ Full paid training
✅ Team uniforms
✅ Real advancement path

No experience required. If you're coachable and willing to work, we'll make you money.

Apply now: epc-contractors.org/careers
Interviews every Tuesday and Thursday in Oldsmar FL""",

    """🔥 ATTENTION TAMPA BAY — EPC Contractors is actively hiring.

Are you tired of jobs that don't pay what you're worth?

We are a licensed solar, HVAC, roofing, and water solutions company building our in-house sales team NOW.

Home Improvement Sales Specialist:
— Setter: $4,000–$8,000/month
— Closer: $8,000–$12,000+/month
— Paid training + benefits + team culture

Apply: epc-contractors.org/careers
Interviews: Tue & Thu, 331 Scarlet Blvd, Oldsmar FL"""
]

# Load state
state = {"last_variation": -1}
if os.path.exists(STATE_FILE):
    try:
        state = json.load(open(STATE_FILE))
    except:
        pass

next_var = (state.get("last_variation", -1) + 1) % 4
post_text = POSTS[next_var]

# Post to Facebook
import urllib.parse
payload = json.dumps({"message": post_text, "access_token": TOKEN})
r = subprocess.run([
    "curl", "-s", "--max-time", "20", "-X", "POST",
    f"https://graph.facebook.com/v20.0/{PAGE_ID}/feed",
    "-H", "Content-Type: application/json",
    "-d", payload
], capture_output=True, text=True)

result = json.loads(r.stdout) if r.stdout.strip() else {}

if result.get("id"):
    state["last_variation"] = next_var
    state["last_posted"] = datetime.now().isoformat()
    json.dump(state, open(STATE_FILE, "w"))
    # Silent on success
else:
    err = result.get("error", {}).get("message", r.stdout[:200])
    print(f"🚨 EPC Recruiting FB Post FAILED (variation {next_var+1}/4): {err}")
    sys.exit(1)
