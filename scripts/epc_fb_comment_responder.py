#!/usr/bin/env python3
"""
EPC Solar FL — Facebook Comment Auto-Responder
Checks for new unanswered comments on the EPC Solar FL page every run
and replies warmly via the Meta Graph API to drive leads / inspections.

State tracked in ~/.hermes/epc_comment_state.json — never double-replies.

Outputs NOTHING when there are no new comments (silent delivery).
Prints a summary when replies are sent (triggers Telegram delivery).
"""

import json
import os
import random
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
PAGE_ID         = "104084848517243"
TOKEN_FILE      = Path.home() / ".hermes" / "epc_page_token.txt"
STATE_FILE      = Path.home() / ".hermes" / "epc_comment_state.json"
GRAPH_VER       = "v19.0"
BASE_URL        = f"https://graph.facebook.com/{GRAPH_VER}"
POST_LOOKBACK   = 7 * 24 * 3600   # 7 days back

CTAS = [
    "DM us or grab a free energy inspection at https://bit.ly/EPCSolarFL — no pressure at all.",
    "Happy to show you what we find — book a free inspection at https://bit.ly/EPCSolarFL or just DM us.",
    "We offer a free energy check — https://bit.ly/EPCSolarFL if you want to see what's really going on.",
    "Send us a DM and we'll walk you through it, or snag a free spot at https://bit.ly/EPCSolarFL.",
    "The inspection is 100% free, no strings — https://bit.ly/EPCSolarFL or just DM us.",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_token() -> str:
    return TOKEN_FILE.read_text().strip().splitlines()[0].strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"replied": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def graph_get(path: str, params: dict, token: str) -> dict:
    params["access_token"] = token
    qs = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/{path}?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Graph GET error {e.code} on /{path}: {body[:400]}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"  Graph GET exception on /{path}: {e}", file=sys.stderr)
        return {}


def graph_post_api(path: str, data: dict, token: str) -> dict:
    data["access_token"] = token
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    url = f"{BASE_URL}/{path}"
    req = urllib.request.Request(url, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Graph POST error {e.code} on /{path}: {body[:400]}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"  Graph POST exception on /{path}: {e}", file=sys.stderr)
        return {}


def get_recent_posts(token: str) -> list:
    data = graph_get(
        f"{PAGE_ID}/posts",
        {"fields": "id,message,created_time", "limit": "25"},
        token,
    )
    posts = data.get("data", [])
    cutoff = time.time() - POST_LOOKBACK
    recent = []
    for p in posts:
        ct = p.get("created_time", "")
        try:
            ts = datetime.fromisoformat(ct.replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = 0
        if ts >= cutoff:
            recent.append(p)
    return recent


def get_comments(post_id: str, token: str) -> list:
    data = graph_get(
        f"{post_id}/comments",
        {
            "fields": "id,message,from,created_time,comments{id,from}",
            "filter": "stream",
            "limit": "50",
        },
        token,
    )
    return data.get("data", [])


def page_already_replied(comment: dict) -> bool:
    """True if the page already has a reply in this comment's thread."""
    sub = comment.get("comments", {}).get("data", [])
    for reply in sub:
        if reply.get("from", {}).get("id") == PAGE_ID:
            return True
    return False


# ── Reply generation ──────────────────────────────────────────────────────────

OPENERS = [
    "Right?! ",
    "Totally get it — ",
    "Ha, exactly! ",
    "You'd be surprised — ",
    "That's what most folks say at first! ",
    "Great point — ",
]

BRIDGES = [
    "Most people had no idea what they were actually paying for until we walked them through it.",
    "A lot of homeowners don't realise how much they're leaving on the table every month.",
    "It really clicks once you see your actual usage breakdown.",
    "So many people are overpaying and don't even know it.",
    "Once you see the numbers side-by-side, it's kind of wild.",
    "The difference before and after is usually pretty eye-opening.",
]

HOOKS = [
    "What's your electric bill running these days?",
    "Are you in Florida? We might be in your area.",
    "Have you ever had anyone look at your home's energy setup?",
    "Would love to show you what we'd find — it's free.",
    "Curious what your setup looks like?",
]


def generate_reply(comment_text: str, cta: str) -> str:
    """Warm, short, human-sounding reply tailored loosely to the comment."""
    t = comment_text.lower()

    if any(w in t for w in ["how much", "cost", "price", "expensive", "afford"]):
        opener = "Great question — "
        bridge = "The cost conversation is way different once you factor in what you're already sending to your utility company."
        hook   = "Want us to run a quick free comparison for your home?"
    elif any(w in t for w in ["scam", "fake", "trust", "legit", "real"]):
        opener = "Totally fair to ask — "
        bridge = "We get that a lot, and honestly it's smart to question it. We're a licensed FL contractor, happy to show receipts 😄"
        hook   = "Feel free to DM us — zero pressure."
    elif any(w in t for w in ["interested", "interest", "tell me more", "more info", "want to know"]):
        opener = "Love to hear it! "
        bridge = "We can walk you through everything — usually takes about 15 minutes."
        hook   = "Want to grab a free inspection slot?"
    elif any(w in t for w in ["already have", "already solar", "have panels", "got solar"]):
        opener = "Nice! "
        bridge = "Even existing systems often have billing quirks or inefficiencies we can spot."
        hook   = "We can take a look for free if you're ever curious."
    elif any(w in t for w in ["save", "saving", "savings", "bill", "electric"]):
        opener = "Yes! "
        bridge = "The savings add up fast once you see what your home actually needs."
        hook   = "What does your electric bill run these days?"
    else:
        opener = random.choice(OPENERS)
        bridge = random.choice(BRIDGES)
        hook   = random.choice(HOOKS)

    return f"{opener}{bridge} {hook}\n\n{cta}\n\n— The EPC Team"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = load_token()
    state = load_state()
    already_replied = set(state.get("replied", []))

    posts = get_recent_posts(token)
    if not posts:
        sys.exit(0)   # silent

    replies_made = []

    for post in posts:
        post_id  = post["id"]
        post_msg = post.get("message", "")[:80]
        comments = get_comments(post_id, token)

        for comment in comments:
            cid   = comment["id"]
            cmsg  = comment.get("message", "").strip()
            cfrom = comment.get("from", {}).get("name", "someone")

            if not cmsg:
                continue
            if cid in already_replied:
                continue
            if page_already_replied(comment):
                already_replied.add(cid)
                continue

            cta          = random.choice(CTAS)
            reply_text   = generate_reply(cmsg, cta)

            result = graph_post_api(f"{cid}/comments", {"message": reply_text}, token)

            if result.get("id"):
                already_replied.add(cid)
                replies_made.append({
                    "from":    cfrom,
                    "comment": cmsg[:120],
                    "reply":   reply_text,
                })
                print(f"Replied to {cfrom}: {cmsg[:60]}")
            else:
                print(f"FAILED reply to comment {cid} from {cfrom}", file=sys.stderr)

            time.sleep(1.5)   # polite rate-limit

    # Persist state
    state["replied"]  = list(already_replied)
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    if not replies_made:
        sys.exit(0)   # silent — nothing went out

    # ── Notification output (only when replies were sent) ─────────────────────
    stamp = datetime.now().strftime("%b %d %I:%M %p")
    print(f"\n💬 **EPC Solar FL — Comment Responder** | {stamp}")
    print(f"Replied to **{len(replies_made)}** new comment(s):\n")
    for r in replies_made:
        print(f"👤 **{r['from']}**: _{r['comment'][:100]}_")
        print(f"   ↳ {r['reply'][:140]}")
        print()


if __name__ == "__main__":
    main()
