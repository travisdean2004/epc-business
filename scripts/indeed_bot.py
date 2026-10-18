#!/usr/bin/env python3
"""
EPC Indeed Bot — fast version. Scrapes candidate list only (no per-profile visits).
Runs in < 20s. Sends new applicants to EPC NEW HIRES chat instantly.
"""
import asyncio, json, os, re, subprocess, time
from playwright.async_api import async_playwright

cfg       = json.load(open(os.path.expanduser("~/epc-webhook/config.json")))
TG_TOKEN  = cfg["TG_BOT_TOKEN"]
NEW_HIRES = "-5306696575"   # EPC NEW HIRES chat
TRAVIS    = "6985623877"
SEEN_FILE = os.path.expanduser("~/epc/seen_indeed.json")

def tg(chat_id, text):
    import urllib.request, urllib.parse
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"TG error: {e}")

def load_seen():
    try: return set(json.load(open(SEEN_FILE)))
    except: return set()

def save_seen(s):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    json.dump(list(s), open(SEEN_FILE, "w"))

def ws_url():
    out = subprocess.check_output("curl -s http://localhost:9222/json/version", shell=True)
    return json.loads(out)["webSocketDebuggerUrl"]

async def main():
    seen = load_seen()
    new_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(ws_url())
        ctx  = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()

        await page.goto(
            "https://employers.indeed.com/candidates?tab=manage&statusName=All",
            wait_until="domcontentloaded", timeout=30000
        )
        # Wait for candidate cards — short wait only
        try:
            await page.wait_for_selector('a[href*="/candidates/view"]', timeout=8000)
        except:
            pass
        await page.wait_for_timeout(2000)

        title = await page.title()
        print(f"Page: {title}")

        # Scrape candidate cards from the LIST page — no individual profile visits
        candidates = await page.evaluate("""
            () => {
                const results = [];
                // Each candidate card
                const cards = [...document.querySelectorAll('[data-testid="candidate-card"], .css-candidate-card, [class*="candidateCard"]')];
                
                if (cards.length > 0) {
                    cards.forEach(card => {
                        const link = card.querySelector('a[href*="/candidates/view"]');
                        const href = link ? link.href : '';
                        const text = card.innerText || '';
                        const nameEl = card.querySelector('h2, h3, [data-testid="candidate-name"], strong');
                        const name = nameEl ? nameEl.innerText.trim() : 
                                     (text.split('\\n')[0] || '').trim();
                        results.push({ href, name, text: text.slice(0, 300) });
                    });
                } else {
                    // Fallback: grab all candidate view links
                    const links = [...document.querySelectorAll('a[href*="/candidates/view"]')];
                    const seen_hrefs = new Set();
                    links.forEach(a => {
                        if (seen_hrefs.has(a.href)) return;
                        seen_hrefs.add(a.href);
                        // Walk up to find the card container
                        let el = a;
                        for (let i = 0; i < 5; i++) {
                            el = el.parentElement;
                            if (!el) break;
                        }
                        const text = el ? el.innerText : a.innerText;
                        const name = a.innerText.trim() || text.split('\\n')[0].trim();
                        results.push({ href: a.href, name: name.slice(0, 60), text: text.slice(0, 300) });
                    });
                }
                return results;
            }
        """)

        print(f"Found {len(candidates)} candidates on list")

        for c in candidates:
            href = c.get("href", "")
            if not href:
                continue

            # Unique ID from URL
            m = re.search(r'id=([^&]+)', href)
            uid = m.group(1) if m else href.split("/")[-1]

            if uid in seen:
                continue

            name = (c.get("name") or "Unknown").strip()
            # Clean up name — remove garbage
            name = re.sub(r'\s+', ' ', name).split('\n')[0][:50]

            card_text = c.get("text", "")
            # Try to extract phone from card text
            phone_m = re.search(r'\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}', card_text)
            phone = phone_m.group(0) if phone_m else "See profile"

            # Job title hint from card
            job = "Sales Rep - Solar"
            if "manager" in card_text.lower():
                job = "Manager role"

            msg = (
                f"🔔 *NEW INDEED APPLICANT*\n\n"
                f"👤 *{name}*\n"
                f"📞 {phone}\n"
                f"💼 {job} | Oldsmar FL\n"
                f"🔗 [View on Indeed]({href})\n\n"
                f"📲 Call within 5 minutes!"
            )
            print(msg)
            tg(NEW_HIRES, msg)

            seen.add(uid)
            new_count += 1

        save_seen(seen)
        await page.close()
        await browser.close()

    if new_count > 0:
        print(f"✅ Sent {new_count} new Indeed applicants to New Hires chat")
    else:
        print("No new applicants")

if __name__ == "__main__":
    asyncio.run(main())
