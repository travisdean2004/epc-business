"""
EPC Facebook Session Saver — v2
Opens a browser, goes to Facebook. Once it detects you're logged in
(sees the feed), it automatically saves the session. No Enter needed.
Just log in and wait 5 seconds.
"""
import asyncio, json
from pathlib import Path

SESSION_FILE = Path.home() / ".hermes" / "fb_session.json"

async def save_session():
    from playwright.async_api import async_playwright

    print("Starting browser...")
    print("A Chrome window will open. Log in as Stephanie.")
    print("Once you see the Facebook feed, wait 5 seconds — it saves automatically.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        await page.goto("https://www.facebook.com/login")

        print("Waiting for you to log in...")

        # Poll until logged in (no longer on login/checkpoint page)
        for i in range(120):  # wait up to 4 minutes
            await asyncio.sleep(2)
            current_url = page.url
            if "facebook.com" in current_url and "login" not in current_url and "checkpoint" not in current_url:
                print(f"Logged in detected! URL: {current_url}")
                print("Waiting 5 more seconds to let page fully load...")
                await asyncio.sleep(5)
                break
            if i % 10 == 0:
                print(f"  Still waiting... ({i*2}s)")
        else:
            print("Timed out waiting for login.")
            await browser.close()
            return

        # Save session
        storage = await context.storage_state()
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            json.dump(storage, f)

        print(f"\n✅ Session saved to {SESSION_FILE}")
        print("You can close the browser window now.")

        await asyncio.sleep(3)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(save_session())
