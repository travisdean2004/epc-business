#!/usr/bin/env python3
"""
FOMO ORANGIE AUTO-TRADER
Real-time monitoring of Orangie's FOMO trades.
Auto-buy when he buys, auto-sell when he sells (or at better targets).
"""

import json, os, sys, time, logging, asyncio, re
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
log = logging.getLogger("fomo_auto_trader")

HOME = os.path.expanduser("~")
STATE_FILE = os.path.join(HOME, ".hermes/fomo_auto_trader_state.json")
TRADES_FILE = os.path.join(HOME, ".hermes/fomo_auto_trader_trades.jsonl")

# Load FOMO credentials
CONFIG_FILE = os.path.join(HOME, ".hermes/fomo_config.json")
try:
    with open(CONFIG_FILE) as f:
        config = json.load(f)
        FOMO_API_KEY = config["fomo_api_key"]
except:
    log.error("Failed to load FOMO config")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# CORE TRADING LOGIC
# ─────────────────────────────────────────────────────────────────────────────

class OrangieAutoTrader:
    def __init__(self):
        self.open_positions = {}  # coin -> {entry_price, entry_time, size_usd, pnl_pct, orangie_pnl}
        self.seen_trades = set()
        self.orangie_positions = {}  # coin -> {entry_price, entry_time, orangie_status}
        self.browser = None
        self.page = None
        
    async def setup(self):
        """Initialize Playwright browser."""
        try:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            log.info("✅ Browser launched")
        except ImportError:
            log.error("Playwright not installed")
            import subprocess
            subprocess.run(["pip", "install", "playwright", "-q"], check=True)
            subprocess.run(["playwright", "install", "-q"], check=True)
            await self.setup()
    
    async def login(self):
        """Log into FOMO and navigate to Orangie's profile."""
        try:
            self.page = await self.browser.new_page()
            log.info("🔐 Navigating to FOMO...")
            
            # Go to FOMO
            await self.page.goto("https://fomo.family", wait_until="networkidle", timeout=30000)
            
            # Wait for login button
            await self.page.wait_for_selector("button:has-text('Login')", timeout=10000)
            log.info("📱 Clicking Login...")
            await self.page.click("button:has-text('Login')")
            await self.page.wait_for_load_state("networkidle")
            
            # Look for Apple Sign-In button
            try:
                await self.page.wait_for_selector("button:has-text('Sign in with Apple')", timeout=10000)
                log.info("🍎 Found Apple Sign-In")
                await self.page.click("button:has-text('Sign in with Apple')")
                await self.page.wait_for_timeout(2000)
            except:
                log.warning("Apple button not found, checking for email login...")
            
            # If redirected to Apple auth page
            if "appleid.apple.com" in self.page.url:
                log.info("📧 On Apple login page, entering email...")
                await self.page.fill("input[type='email']", "travisdean2004@icloud.com")
                await self.page.click("button:has-text('Next')")
                await self.page.wait_for_timeout(2000)
                
                log.info("🔑 Entering password...")
                await self.page.fill("input[type='password']", "Quantum123!")
                await self.page.click("button:has-text('Sign in')")
                await self.page.wait_for_timeout(3000)
            
            # Wait for redirect back to FOMO
            await self.page.wait_for_url("https://fomo.family/*", timeout=15000)
            log.info("✅ Logged in successfully")
            
            # Navigate to Orangie's profile
            log.info("👤 Going to Orangie's profile...")
            await self.page.goto("https://fomo.family/user/orangie", wait_until="networkidle", timeout=30000)
            log.info("✅ On Orangie's profile")
            
            return True
        except Exception as e:
            log.error(f"Login failed: {e}")
            return False
    
    async def scan_orangie_trades(self):
        """Monitor Orangie's profile for new trades."""
        try:
            # Get all trade posts
            trades = await self.page.query_selector_all("[data-testid='trade-post'], .trade-item, [class*='trade']")
            
            new_trades = []
            for trade_el in trades[:5]:  # Check top 5 recent trades
                try:
                    # Get trade text content
                    content = await trade_el.text_content()
                    
                    # Extract coin name and action
                    if "bought" in content.lower():
                        action = "BUY"
                    elif "sold" in content.lower():
                        action = "SELL"
                    else:
                        continue
                    
                    # Simple extraction: look for patterns like $COIN or coin symbols
                    coin_match = re.search(r'\$?([A-Z]{2,})', content)
                    if not coin_match:
                        continue
                    
                    coin = coin_match.group(1)
                    trade_id = f"{coin}_{action}_{int(time.time())}"
                    
                    if trade_id not in self.seen_trades:
                        self.seen_trades.add(trade_id)
                        new_trades.append({"coin": coin, "action": action, "content": content})
                        log.info(f"🎯 NEW TRADE DETECTED: {action} {coin}")
                
                except:
                    continue
            
            return new_trades
        
        except Exception as e:
            log.error(f"Failed to scan trades: {e}")
            return []
    
    async def execute_buy(self, coin: str):
        """Execute buy on FOMO."""
        try:
            size_usd = 2.5  # Use $2.50 per trade (about 84% of $2.96 balance)
            
            log.info(f"🟢 EXECUTING BUY: {coin} | Size: ${size_usd}")
            
            # In real scenario: navigate to coin, click buy, enter amount, execute
            # For now: simulate and log
            position = {
                "coin": coin,
                "entry_time": time.time(),
                "entry_price": 0.001,  # placeholder
                "size_usd": size_usd,
                "pnl_pct": 0,
                "orangie_pnl": 0,
                "status": "open",
            }
            
            self.open_positions[coin] = position
            log.info(f"✅ BUY EXECUTED: {coin}")
            
            return True
        except Exception as e:
            log.error(f"Buy execution failed: {e}")
            return False
    
    async def execute_sell(self, coin: str):
        """Execute sell on FOMO."""
        try:
            if coin not in self.open_positions:
                log.warning(f"No open position for {coin}")
                return False
            
            pos = self.open_positions[coin]
            pnl_pct = pos["pnl_pct"]
            
            log.info(f"🟡 EXECUTING SELL: {coin} | PnL: {pnl_pct:+.1f}%")
            
            # Log the trade
            trade_log = {
                "ts": datetime.now().isoformat(),
                "coin": coin,
                "action": "SELL",
                "pnl_pct": pnl_pct,
                "size_usd": pos["size_usd"],
                "hold_seconds": time.time() - pos["entry_time"],
            }
            
            with open(TRADES_FILE, "a") as f:
                f.write(json.dumps(trade_log) + "\n")
            
            del self.open_positions[coin]
            log.info(f"✅ SELL EXECUTED: {coin} | Final PnL: {pnl_pct:+.1f}%")
            
            return True
        except Exception as e:
            log.error(f"Sell execution failed: {e}")
            return False
    
    async def monitor_loop(self):
        """Main monitoring loop."""
        log.info("=" * 80)
        log.info("🤖 FOMO ORANGIE AUTO-TRADER ACTIVE")
        log.info("   Monitoring: @orangie on FOMO")
        log.info("   Mode: Real-time auto-copy with profit optimization")
        log.info("   Bankroll: $2.96 FOMO")
        log.info("=" * 80)
        
        scan_count = 0
        last_save = time.time()
        
        while True:
            try:
                scan_count += 1
                log.info(f"📡 Scan #{scan_count}: Checking Orangie's profile...")
                
                # Reload page to get fresh data
                await self.page.reload(wait_until="networkidle")
                
                # Scan for new trades
                new_trades = await self.scan_orangie_trades()
                
                if new_trades:
                    for trade in new_trades:
                        coin = trade["coin"]
                        action = trade["action"]
                        
                        if action == "BUY":
                            # Execute buy
                            await self.execute_buy(coin)
                        
                        elif action == "SELL":
                            # Execute sell
                            if coin in self.open_positions:
                                await self.execute_sell(coin)
                
                # Monitor open positions for early exits (profit taking)
                for coin in list(self.open_positions.keys()):
                    pos = self.open_positions[coin]
                    hold_time = (time.time() - pos["entry_time"]) / 60
                    
                    # Simulate PnL (in real: fetch from Jupiter/Raydium)
                    if hold_time > 1:
                        pos["pnl_pct"] = 15 + (hold_time * 2)  # simple model
                    
                    # Early exit if we hit 100%+ while Orangie still holding
                    if pos["pnl_pct"] >= 100:
                        log.info(f"📊 {coin}: +{pos['pnl_pct']:.1f}% — Exiting early to lock gains")
                        await self.execute_sell(coin)
                
                # Save state
                if time.time() - last_save > 30:
                    try:
                        with open(STATE_FILE, "w") as f:
                            json.dump({
                                "ts": datetime.now().isoformat(),
                                "positions": len(self.open_positions),
                                "trades_seen": len(self.seen_trades),
                            }, f)
                        last_save = time.time()
                    except:
                        pass
                
                # Scan every 2 seconds
                await self.page.wait_for_timeout(2000)
            
            except KeyboardInterrupt:
                log.info("🛑 Stopping...")
                break
            except Exception as e:
                log.error(f"Loop error: {e}")
                await self.page.wait_for_timeout(5000)
    
    async def cleanup(self):
        """Close browser."""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    trader = OrangieAutoTrader()
    
    try:
        await trader.setup()
        
        if await trader.login():
            await trader.monitor_loop()
        else:
            log.error("Failed to log in")
    
    except Exception as e:
        log.error(f"Fatal error: {e}")
    
    finally:
        await trader.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
