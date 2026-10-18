"""
EPC Facebook Group Auto-Poster
Runs via Hermes cron — posts daily content to all 8 EPC groups.
Uses saved session cookies so no login needed after first run.
"""
import asyncio, json, os, sys, random, time
from pathlib import Path
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────
SESSION_FILE = Path.home() / ".hermes" / "fb_session.json"
CONTENT_FILE = Path.home() / ".hermes" / "fb_group_content.json"

# The 8 groups Travis joined
GROUPS = [
    {"id": "189874673637",    "name": "Florida Solar Power",           "type": "leads"},
    {"id": "271625487184735", "name": "Going Solar in Florida",        "type": "leads"},
    {"id": "1395271155768039","name": "Florida Solar Savings & Tips",  "type": "owned"},
    {"id": "solarobjections", "name": "Solar Community Forum",         "type": "recruit_pro"},
    {"id": "192772701642340", "name": "Solarpreneurs",                 "type": "recruit_pro"},
    {"id": "1504897529772614","name": "D2D Solar Experts",             "type": "recruit_d2d"},
    {"id": "D2Dcantknockthis","name": "Door to Door Sales TRIBE",     "type": "recruit_d2d"},
    {"id": "362611775128759", "name": "Solar Jobs USA",                "type": "jobs"},
]

def pick_post(group_type: str, posts: dict) -> str:
    """Pick appropriate post content for group type."""
    options = posts.get(group_type, posts.get("leads", []))
    if not options:
        return None
    return random.choice(options)

def spintax(text: str) -> str:
    """Resolve {option1|option2|option3} spintax into one variant."""
    import re
    while "{" in text:
        text = re.sub(r'\{([^{}]+)\}', lambda m: random.choice(m.group(1).split("|")), text)
    return text

async def post_to_group(page, group_id: str, group_name: str, message: str) -> bool:
    """Navigate to group and post a message."""
    from playwright.async_api import TimeoutError as PWTimeout
    try:
        url = f"https://www.facebook.com/groups/{group_id}"
        print(f"  Navigating to {group_name}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(3, 6))

        # Click the post composer
        clicked = False
        composer_selectors = [
            'span:has-text("Write something")',
            'div[aria-label="Create a public post…"]',
            'div[aria-placeholder="Create a public post…"]',
        ]
        for sel in composer_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3000):
                    await el.click()
                    clicked = True
                    print(f"  Composer opened via: {sel[:50]}")
                    break
            except:
                continue

        if not clicked:
            print(f"  SKIP: Could not open composer for {group_name}")
            return False

        await asyncio.sleep(random.uniform(2, 3))

        # Click at coordinates where the post dialog textbox appears (top ~363-400)
        # This bypasses all overlay/focus issues with Facebook's Lexical editor
        typed = False
        try:
            import subprocess as sp
            sp.run(['pbcopy'], input=message.encode('utf-8'), capture_output=True)
            await asyncio.sleep(0.3)

            # Click in the middle of the dialog at the textbox position
            await page.mouse.click(640, 380)
            await asyncio.sleep(0.5)
            await page.keyboard.press('Meta+v')
            await asyncio.sleep(1.0)

            # Verify text landed in the post box
            result = await page.evaluate("""
                () => {
                    const boxes = Array.from(document.querySelectorAll('[role="textbox"]'));
                    const postBox = boxes.find(b =>
                        b.getAttribute('aria-placeholder') === 'Create a public post\u2026' ||
                        b.getAttribute('aria-placeholder') === 'Create a public post...'
                    );
                    return postBox ? {ok: true, length: postBox.innerText.trim().length} : {ok: false};
                }
            """)
            if result.get('ok') and result.get('length', 0) > 5:
                typed = True
                print(f"  Message typed ({result['length']} chars)")
        except Exception as e:
            print(f"  Typing failed: {e}")

        if not typed:
            print(f"  SKIP: Could not type in {group_name}")
            return False

        await asyncio.sleep(random.uniform(2, 3))

        # Click Post button
        post_selectors = [
            'div[aria-label="Post"][role="button"]',
            'button[aria-label="Post"]',
            'div[role="button"]:has-text("Post")',
        ]
        posted = False
        for sel in post_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=3000):
                    await btn.click()
                    posted = True
                    print(f"  ✅ Posted to {group_name}")
                    break
            except:
                continue

        if not posted:
            print(f"  FAIL: Could not click Post in {group_name}")
            return False

        # Human-like delay between groups
        await asyncio.sleep(random.uniform(90, 150))
        return True

    except PWTimeout:
        print(f"  TIMEOUT: {group_name}")
        return False
    except Exception as e:
        print(f"  ERROR in {group_name}: {e}")
        return False

async def run():
    from playwright.async_api import async_playwright

    # Load session
    if not SESSION_FILE.exists():
        print("ERROR: No saved Facebook session. Run the login script first.")
        print(f"Expected session file: {SESSION_FILE}")
        sys.exit(1)

    with open(SESSION_FILE) as f:
        storage_state = json.load(f)

    # Load today's content
    if not CONTENT_FILE.exists():
        print("ERROR: No content file found at", CONTENT_FILE)
        sys.exit(1)

    with open(CONTENT_FILE) as f:
        posts = json.load(f)

    print(f"\n🤖 EPC Group Poster — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Groups to post in: {len(GROUPS)}")

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # must be visible for Facebook's Lexical editor to work with coordinates
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-position=3000,3000",  # off-screen so it doesn't interrupt
                "--window-size=1280,900",
                f"--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            ]
        )

        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Remove webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)

        page = await context.new_page()

        # Verify session is valid
        print("\nVerifying Facebook session...")
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if "login" in page.url.lower() or "checkpoint" in page.url.lower():
            print("SESSION EXPIRED — need to re-run login script")
            await browser.close()
            sys.exit(1)

        print("Session valid ✅")

        # Post to each group
        for group in GROUPS:
            message_template = pick_post(group["type"], posts)
            if not message_template:
                print(f"  SKIP {group['name']}: no content for type {group['type']}")
                continue

            message = spintax(message_template)
            success = await post_to_group(page, group["id"], group["name"], message)
            results.append({"group": group["name"], "success": success})

        await browser.close()

    # Summary
    succeeded = sum(1 for r in results if r["success"])
    failed = [r["group"] for r in results if not r["success"]]
    print(f"\n📊 Done: {succeeded}/{len(results)} groups posted")
    if failed:
        print(f"Failed: {', '.join(failed)}")

    # Output for cron delivery
    print(f"\n✅ EPC Group Posts: {succeeded}/{len(results)} groups posted successfully")
    if failed:
        print(f"⚠️ Failed: {', '.join(failed)}")

if __name__ == "__main__":
    asyncio.run(run())
