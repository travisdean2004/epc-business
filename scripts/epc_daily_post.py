#!/usr/bin/env python3
"""
EPC Solar FL — Daily 6PM Facebook Post
Rotates through day-of-week angles. Human, short, real. No corporate speak.
"""
import datetime
import json
import requests

# Config
PAGE_ID = "104084848517243"
TOKEN_FILE = "/Users/tdizzlewizzle/.hermes/epc_page_token.txt"

# Read token
with open(TOKEN_FILE, "r") as f:
    lines = [l.strip() for l in f.read().splitlines() if l.strip()]
PAGE_TOKEN = lines[0]

# Day of week (0=Mon, 6=Sun)
today = datetime.datetime.now()
dow = today.weekday()
day_name = today.strftime("%A")

posts = {
    0: """Just got off the phone with a family in Lakeland who's been paying $340 a month to Duke. Every single month. For years.

They scheduled their free energy inspection on a whim. Didn't expect much.

Now they're locking in at $0 electric. New panels, new roof, zero out of pocket.

That call changed their whole financial situation. Might change yours too.

DM us or comment CHECK and we'll reach out. Takes 10 minutes.

— The EPC Team""",

    1: """Most people don't know this about solar in Florida...

The state has some of the best solar incentives in the country. And most homeowners who qualify never use them because nobody told them.

We're talking no money down. No loan payments that break your budget. Programs built specifically so families can stop paying the power company and start keeping that money.

Florida sunlight is free. Your electric bill doesn't have to exist.

Comment INFO or DM us and we'll break it all down for you — no pressure.

— The EPC Team""",

    2: """June in Florida and your AC is working overtime.

You already know what that electric bill looks like. $350. $400. Maybe more if you've got a bigger house.

And it's only getting hotter.

Here's the thing — your neighbors who went solar? They're not stressed about it. Not one bit.

If you've been putting this off, this is your sign. Free energy inspection. Real answers. Zero commitment.

DM us today. Let's get you out of this cycle.

— The EPC Team""",

    3: """Our installer D'Vante just finished up in Brandon today. Clean job. Happy family.

This is the part nobody sees on social media — the prep work, the precision, making sure every panel is locked in perfect before we leave.

D'Vante's been doing this for years. Takes pride in every roof he touches.

The family came outside at the end and just smiled. Said it felt real now.

That's why we do this. Real homes. Real people. Real results.

If you want to be next — DM us. Free inspection, zero hassle.

— The EPC Team""",

    4: """Before you spend another $400 next month...

It's Friday. You made it through the week. Last thing you want to think about is another massive electric bill coming in 30 days.

But here's a thought — what if next month was different?

We've got open slots this weekend for free virtual energy inspections. 10 minutes. We pull up your info, tell you what you qualify for, and you decide from there.

No hard sell. No contracts on the call. Just real info.

DM us FRIDAY and let's make next month look different.

— The EPC Team""",

    5: """Another Saturday, another family going to $0 electric. 🙌

We wrapped up an install in Wesley Chapel this morning. Family had been paying $380/month. Kids running around, AC blasting all summer — you know how it is.

This morning? System turned on. Bill goes to zero.

Dad texted us after: "I wish I did this 3 years ago."

If you've been thinking about it — stop thinking. DM us, take 10 minutes this weekend, and find out if you qualify. Most people do.

— The EPC Team""",

    6: """Start your week right — book your free energy inspection before Monday hits.

Takes 10 minutes. We look at your home, your current bill, your roof — and tell you exactly what programs you qualify for.

Solar. New AC. New roof. Sometimes all three. Zero out of pocket for families who qualify.

Sunday is a great day to make a decision that changes the next 25 years of electric bills.

Drop a comment or DM us. We'll get you set up first thing.

— The EPC Team""",
}

message = posts.get(dow, posts[0])

# Post to Facebook
url = f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed"
resp = requests.post(url, data={"message": message, "access_token": PAGE_TOKEN})
data = resp.json()

post_id = data.get("id")
error = data.get("error", {}).get("message") if "error" in data else None

if post_id:
    print(f"✅ EPC Solar FB Post LIVE — {day_name}")
    print(f"Post ID: {post_id}")
    print(f"\n--- POST CONTENT ---\n{message}")
else:
    print(f"❌ Post FAILED — {day_name}")
    print(f"Error: {error}")
    print(f"Full response: {json.dumps(data, indent=2)}")
