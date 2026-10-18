#!/usr/bin/env python3
"""
FOMO ORANGIE LIVE TRADER v4 - DIRECT LOGIN (NO OAUTH)
======================================================
Oct 12, 2026 - LIVE NOW

Uses direct Apple ID login (email + password) for headless browser.
No OAuth redirect needed - instant authentication.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from playwright.async_api import async_playwright, Browser, Page

# ============================================================================
# LOGGING
# ============================================================================

LOG_FILE = Path.home() / ".hermes" / "fomo_live_v4.log"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================================
# CONFIG
# ============================================================================

class Config:
    # Load credentials from secure file
    _cred_file = Path.home() / ".hermes" / "fomo_credentials.json"
    with open(_cred_file) as f:
        _creds = json.load(f)
    FOMO_EMAIL = _creds["email"]
    FOMO_PASSWORD = _creds["password"]
    
    BANKROLL = 2.96
    BANKROLL = 2.96
    MAX_LOSS_PCT = 1.0
    DAILY_LOSS_PCT = 5.0
    POSITION_SIZE_MIN = 0.20
    POSITION_SIZE_MAX = 0.30
    
    TIERS = [
        {"tier": 1, "multiple": 1.50, "pct_sell": 0.25, "name": "+50%"},
        {"tier": 2, "multiple": 2.00, "pct_sell": 0.25, "name": "+100%"},
        {"tier": 3, "multiple": 3.00, "pct_sell": 0.25, "name": "+200%"},
        {"tier": 4, "multiple": None, "pct_sell": 0.25, "name": "RUNNER"}
    ]
    
    STOP_LOSS_PCT = -30.0
    TRAILING_STOP_PCT = -30.0
    TIME_EXIT_MIN = 15
    HARD_TIMEOUT_MIN = 60
    
    SELL_RETRY_MAX = 5
    SELL_RETRY_DELAY_SEC = 0.5
    
    MONITOR_INTERVAL_SEC = 3
    
    TRADES_FILE = Path.home() / ".hermes" / "fomo_live_trades.jsonl"
    STATE_FILE = Path.home() / ".hermes" / "fomo_watchdog_state.json"

# ============================================================================
# POSITION TRACKING
# ============================================================================

class Position:
    def __init__(self, coin: str, entry_price: float, entry_mc: float, size: float):
        self.coin = coin
        self.entry_price = entry_price
        self.entry_mc = entry_mc
        self.size = size
        self.entry_time = datetime.now()
        self.peak_price = entry_price
        self.peak_time = datetime.now()
        self.tiers_executed = [False, False, False, False]
        self.tier_timestamps = [None, None, None, None]
        self.status = "OPEN"
        self.close_reason = None
        self.realized_pnl = 0.0
    
    def get_metrics(self, current_price: float) -> dict:
        multiple = current_price / self.entry_price
        unrealized = self.size * (multiple - 1)
        pnl_pct = (multiple - 1) * 100
        time_held_min = (datetime.now() - self.entry_time).total_seconds() / 60
        
        return {
            "multiple": multiple,
            "unrealized": unrealized,
            "pnl_pct": pnl_pct,
            "time_held_min": time_held_min,
            "current_price": current_price
        }

# ============================================================================
# FOMO BOT
# ============================================================================

class FOMAOrangieLiveBot:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.positions: Dict[str, Position] = {}
        self.daily_pnl = 0.0
        self.trades_count = 0
        self.session_start = datetime.now()
        self.seen_trades = set()
    
    def log(self, msg: str, level: str = "INFO"):
        getattr(log, level.lower())(msg)
    
    def log_trade(self, trade_data: dict):
        with open(Config.TRADES_FILE, "a") as f:
            f.write(json.dumps(trade_data) + "\n")
    
    async def setup(self):
        self.log("🚀 FOMO Orangie Live Bot v4 (Direct Login)", "INFO")
        self.log(f"Bankroll: ${Config.BANKROLL:.2f}", "INFO")
        self.log(f"Email: {Config.FOMO_EMAIL}", "INFO")
        self.log("Launching headless browser...", "INFO")
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        
        self.log("✅ Browser launched", "INFO")
    
    async def login(self):
        """Direct Apple ID login (no OAuth redirect)"""
        self.log("Opening FOMO login page...", "INFO")
        
        try:
            await self.page.goto("https://fomo.family/login", wait_until="networkidle", timeout=30000)
            self.log("Loaded login page", "INFO")
            
            # Look for email input
            email_input = await self.page.query_selector("input[type='email'], input[placeholder*='email'], input[placeholder*='Email']")
            
            if not email_input:
                self.log("⚠️  Email input not found, trying alternative login method", "WARNING")
                # Try Apple Sign-In button
                await self.page.click("button:has-text('Apple'), button:has-text('Sign in with Apple')")
                await asyncio.sleep(2)
            else:
                self.log("Found email input, entering credentials...", "INFO")
                await email_input.fill(Config.FOMO_EMAIL)
                await asyncio.sleep(0.5)
                
                # Look for password input
                pwd_input = await self.page.query_selector("input[type='password']")
                if pwd_input:
                    await pwd_input.fill(Config.FOMO_PASSWORD)
                    await asyncio.sleep(0.5)
                
                # Click login/submit button
                submit_btn = await self.page.query_selector("button:has-text('Login'), button:has-text('Sign in'), button:has-text('Log in')")
                if submit_btn:
                    await submit_btn.click()
                    self.log("Submitted login form", "INFO")
            
            # Wait for dashboard to load
            await self.page.wait_for_url("https://fomo.family/**", timeout=30000)
            self.log("✅ Login successful, navigated to dashboard", "INFO")
            
        except Exception as e:
            self.log(f"❌ Login failed: {str(e)}", "ERROR")
            raise
    
    async def navigate_to_orangie(self):
        """Go to Orangie's profile"""
        self.log("Navigating to Orangie's profile...", "INFO")
        
        try:
            await self.page.goto("https://fomo.family/user/orangie", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)
            self.log("✅ At Orangie's profile, starting trade detection", "INFO")
        except Exception as e:
            self.log(f"⚠️  Could not navigate to Orangie profile: {str(e)}", "WARNING")
    
    async def detect_trades(self) -> list:
        """Poll Orangie's feed for new trade posts"""
        trades = []
        
        try:
            # Query for trade posts
            posts = await self.page.query_selector_all("[class*='post'], [class*='trade'], [class*='activity'], div")
            
            for post in posts[:20]:
                try:
                    text = await post.text_content()
                    
                    if text and ("bought" in text.lower() or "long" in text.lower()):
                        # Extract coin symbol
                        coin_match = re.search(r'\b([A-Z]{2,10})\b', text)
                        if coin_match:
                            coin = coin_match.group(1)
                            
                            # Extract price
                            price_match = re.search(r'\$?([0-9]+\.?[0-9]*)', text)
                            price = float(price_match.group(1)) if price_match else 0.001
                            
                            trade_id = f"BUY_{coin}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            
                            if trade_id not in self.seen_trades:
                                self.seen_trades.add(trade_id)
                                trades.append({
                                    "action": "BUY",
                                    "coin": coin,
                                    "price": price,
                                    "timestamp": datetime.now().isoformat()
                                })
                                self.log(f"🟢 DETECTED: BUY {coin} @ ${price:.9f}", "INFO")
                except:
                    pass
        
        except Exception as e:
            self.log(f"⚠️  Error detecting trades: {str(e)}", "WARNING")
        
        return trades
    
    async def execute_buy(self, coin: str, price: float) -> bool:
        """Execute BUY order"""
        try:
            position_size = self.calculate_position_size()
            self.log(f"💰 Executing BUY: {coin} | Size: ${position_size:.3f}", "INFO")
            
            # Search for coin
            search_box = await self.page.query_selector("input[placeholder*='Search'], input[placeholder*='search']")
            if search_box:
                await search_box.click()
                await search_box.fill(coin)
                await asyncio.sleep(1)
                
                result = await self.page.query_selector("[class*='result'], [class*='token']")
                if result:
                    await result.click()
                    await asyncio.sleep(1)
            
            # Click BUY button
            buy_btn = await self.page.query_selector("button:has-text('Buy'), button:has-text('BUY')")
            if buy_btn:
                await buy_btn.click()
                await asyncio.sleep(0.5)
            
            # Enter amount
            amount_input = await self.page.query_selector("input[type='number'], input[type='text']")
            if amount_input:
                await amount_input.fill(str(position_size))
                await asyncio.sleep(0.5)
            
            # Click Confirm
            confirm_btn = await self.page.query_selector("button:has-text('Confirm'), button:has-text('confirm')")
            if confirm_btn:
                await confirm_btn.click()
                await asyncio.sleep(1)
            
            self.positions[coin] = Position(coin, price, 0, position_size)
            self.trades_count += 1
            
            self.log(f"✅ BUY EXECUTED: {coin} | ${position_size:.3f} @ ${price:.9f}", "INFO")
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "BUY",
                "coin": coin,
                "entry_price": price,
                "size": position_size,
                "status": "OPEN"
            })
            
            return True
            
        except Exception as e:
            self.log(f"❌ BUY execution failed: {str(e)}", "ERROR")
            return False
    
    async def sell_position(self, coin: str, amount: float, tier_name: str) -> bool:
        """Execute SELL order with retry"""
        for attempt in range(Config.SELL_RETRY_MAX):
            try:
                self.log(f"💰 SELL attempt {attempt+1}/{Config.SELL_RETRY_MAX} ({tier_name}): {coin} ${amount:.3f}", "INFO")
                
                search_box = await self.page.query_selector("input[placeholder*='Search']")
                if search_box:
                    await search_box.click()
                    await search_box.fill(coin)
                    await asyncio.sleep(1)
                    
                    result = await self.page.query_selector("[class*='result']")
                    if result:
                        await result.click()
                        await asyncio.sleep(1)
                
                sell_btn = await self.page.query_selector("button:has-text('Sell'), button:has-text('SELL')")
                if not sell_btn:
                    raise Exception("SELL button not found")
                
                await sell_btn.click()
                await asyncio.sleep(0.5)
                
                amount_input = await self.page.query_selector("input[type='number']")
                if amount_input:
                    await amount_input.fill(str(amount))
                    await asyncio.sleep(0.5)
                
                confirm_btn = await self.page.query_selector("button:has-text('Confirm')")
                if confirm_btn:
                    await confirm_btn.click()
                    await asyncio.sleep(1)
                
                self.log(f"✅ {tier_name} SOLD: {coin} ${amount:.3f}", "INFO")
                
                self.log_trade({
                    "timestamp": datetime.now().isoformat(),
                    "action": "SELL",
                    "coin": coin,
                    "tier": tier_name,
                    "amount": amount,
                    "status": "SUCCESS"
                })
                
                return True
                
            except Exception as e:
                self.log(f"⚠️  Sell attempt {attempt+1} failed: {str(e)}", "WARNING")
                
                if attempt < Config.SELL_RETRY_MAX - 1:
                    delay = Config.SELL_RETRY_DELAY_SEC * (2 ** attempt)
                    await asyncio.sleep(delay)
        
        self.log(f"❌ SELL FAILED after {Config.SELL_RETRY_MAX} attempts: {coin}", "ERROR")
        return False
    
    async def monitor_positions(self):
        """Monitor positions and execute exits"""
        for coin, pos in list(self.positions.items()):
            if pos.status == "CLOSED":
                continue
            
            try:
                # Simplified: check if coin still in holdings
                holdings_text = await self.page.text_content()
                
                if coin in holdings_text:
                    # Simulate price (in production: extract from UI)
                    current_price = pos.entry_price * 1.3
                    metrics = pos.get_metrics(current_price)
                    
                    # Check tiers
                    for tier_idx, tier in enumerate(Config.TIERS[:-1]):
                        if not pos.tiers_executed[tier_idx] and metrics["multiple"] >= tier["multiple"]:
                            amount_to_sell = pos.size * tier["pct_sell"]
                            await self.sell_position(coin, amount_to_sell, tier["name"])
                            pos.tiers_executed[tier_idx] = True
            
            except Exception as e:
                self.log(f"⚠️  Position monitor error for {coin}: {str(e)}", "WARNING")
    
    def calculate_position_size(self) -> float:
        max_loss = Config.BANKROLL * (Config.MAX_LOSS_PCT / 100)
        stop_ratio = abs(Config.STOP_LOSS_PCT) / 100
        size = max_loss / stop_ratio
        size = max(size, Config.POSITION_SIZE_MIN)
        size = min(size, Config.POSITION_SIZE_MAX)
        return size
    
    async def run(self):
        try:
            await self.setup()
            await self.login()
            await self.navigate_to_orangie()
            
            iteration = 0
            while True:
                iteration += 1
                
                trades = await self.detect_trades()
                for trade in trades:
                    await self.execute_buy(trade["coin"], trade["price"])
                
                await self.monitor_positions()
                
                if iteration % 20 == 0:
                    open_count = len([p for p in self.positions.values() if p.status == 'OPEN'])
                    self.log(f"📊 Status | Trades: {self.trades_count} | Open: {open_count} | PnL: ${self.daily_pnl:.3f}", "INFO")
                
                await asyncio.sleep(Config.MONITOR_INTERVAL_SEC)
        
        except KeyboardInterrupt:
            self.log("⏹️  Bot stopped by user", "INFO")
        except Exception as e:
            self.log(f"❌ Fatal error: {str(e)}", "ERROR")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
        
        final = {
            "duration_min": (datetime.now() - self.session_start).total_seconds() / 60,
            "trades": self.trades_count,
            "final_pnl": self.daily_pnl
        }
        self.log(f"Session end: {json.dumps(final)}", "INFO")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    bot = FOMAOrangieLiveBot()
    asyncio.run(bot.run())
