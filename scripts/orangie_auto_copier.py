#!/usr/bin/env python3
"""
ORANGIE AUTO-COPIER BOT
Monitor Orangie's FOMO profile, auto-copy every trade he makes.
Real-time, 24/7, zero manual clicks.
"""

import json, os, sys, time, logging, asyncio, subprocess
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
log = logging.getLogger("orangie_copier")

HOME = os.path.expanduser("~")
STATE_FILE = os.path.join(HOME, ".hermes/orangie_copier_state.json")
TRADES_FILE = os.path.join(HOME, ".hermes/orangie_copies.jsonl")

# ─────────────────────────────────────────────────────────────────────────────
# CORE: Use browser-based approach with Playwright
# ─────────────────────────────────────────────────────────────────────────────

async def setup_browser():
    """Launch browser with Playwright."""
    try:
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True)
        return browser, p
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright")
        log.info("Installing playwright browsers...")
        subprocess.run(["playwright", "install"], check=True)
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True)
        return browser, p

async def login_fomo(browser, email: str, password: str):
    """Log into FOMO via Apple Sign-In."""
    page = await browser.new_page()
    
    try:
        log.info("🔐 Navigating to FOMO login...")
        await page.goto("https://fomo.family/login", wait_until="networkidle")
        
        # Look for Apple Sign-In button
        log.info("🍎 Clicking Apple Sign-In...")
        await page.click("button:has-text('Sign in with Apple')")
        
        # Wait for Apple login redirect
        await page.wait_for_load_state("networkidle")
        
        # Check if we're on Apple's OAuth page
        if "appleid.apple.com" in page.url:
            log.info("📧 Entering Apple ID email...")
            await page.fill("input[type='email']", email)
            await page.click("button:has-text('Next')")
            await page.wait_for_timeout(2000)
            
            log.info("🔑 Entering password...")
            await page.fill("input[type='password']", password)
            await page.click("button:has-text('Sign in')")
            await page.wait_for_load_state("networkidle")
        
        # Confirm we're logged in
        await page.wait_for_url("https://fomo.family/*", wait_until="networkidle")
        log.info("✅ Logged into FOMO")
        
        return page
    
    except Exception as e:
        log.error(f"Login failed: {e}")
        await page.close()
        return None

async def monitor_orangie_profile(page):
    """Monitor Orangie's profile for new trades."""
    try:
        log.info("📍 Navigating to Orangie's profile...")
        await page.goto("https://fomo.family/user/orangie", wait_until="networkidle")
        
        seen_trades = set()
        
        while True:
            log.info("🔍 Scanning Orangie's recent trades...")
            
            # Get all trade cards on the page
            trades = await page.query_selector_all("div[data-testid='trade-card']")
            
            for trade_el in trades:
                try:
                    # Extract trade ID (unique identifier)
                    trade_id = await trade_el.get_attribute("data-trade-id")
                    
                    if trade_id in seen_trades:
                        continue  # Already copied
                    
                    seen_trades.add(trade_id)
                    
                    # Extract trade details
                    coin_name = await trade_el.text_content()
                    log.info(f"🎯 NEW TRADE: {coin_name}")
                    
                    # Look for "Copy Trade" button within this trade card
                    copy_btn = await trade_el.query_selector("button:has-text('Copy Trade')")
                    
                    if copy_btn:
                        log.info(f"🔄 CLICKING COPY TRADE for {coin_name}...")
                        await copy_btn.click()
                        await page.wait_for_timeout(1000)
                        
                        # Confirm copy (look for confirmation toast)
                        try:
                            await page.wait_for_selector("div:has-text('Trade copied')", timeout=5000)
                            log.info(f"✅ COPIED: {coin_name}")
                            
                            # Log the trade
                            trade_log = {
                                "ts": datetime.now().isoformat(),
                                "coin": coin_name,
                                "status": "copied",
                            }
                            
                            with open(TRADES_FILE, "a") as f:
                                f.write(json.dumps(trade_log) + "\n")
                        except:
                            log.warning(f"No confirmation for {coin_name}")
                    else:
                        log.warning(f"No Copy button found for {coin_name}")
                
                except Exception as e:
                    log.error(f"Error processing trade: {e}")
                    continue
            
            # Refresh every 5 seconds
            log.info("⏰ Waiting 5 seconds before next scan...")
            await page.wait_for_timeout(5000)
            await page.reload()
    
    except Exception as e:
        log.error(f"Monitor loop error: {e}")

async def main():
    log.info("=" * 80)
    log.info("🤖 ORANGIE AUTO-COPIER BOT")
    log.info("   Email: travisdean2004@icloud.com")
    log.info("   Target: @orangie (FOMO)")
    log.info("   Mode: Auto-copy every trade, 24/7")
    log.info("=" * 80)
    
    # Load credentials
    email = "travisdean2004@icloud.com"
    password = "Quantum123!"
    
    # Launch browser
    log.info("🚀 Launching browser...")
    browser, playwright = await setup_browser()
    
    try:
        # Login
        page = await login_fomo(browser, email, password)
        if not page:
            log.error("Failed to login, exiting")
            return
        
        # Monitor Orangie's trades
        await monitor_orangie_profile(page)
    
    except KeyboardInterrupt:
        log.info("🛑 Stopping...")
    except Exception as e:
        log.error(f"Fatal error: {e}")
    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    asyncio.run(main())
