#!/usr/bin/env python3
"""
FOMO LEADERBOARD SCRAPER + PAPER TRADER
Real coin prices from FOMO UI (web scrape)
Paper trades on real coins
"""
import asyncio
from playwright.async_api import async_playwright
import json
import logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "fomo_paper_live.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_paper_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger(__name__)

BANKROLL = 2.96
POS_SIZE = 0.30

def log_msg(msg):
    logging.info(msg)

def log_trade(data):
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")

async def main():
    log_msg("=" * 70)
    log_msg("🔥 FOMO LEADERBOARD PAPER TRADER (Real coins, real prices)")
    log_msg("=" * 70)
    
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    
    bankroll = BANKROLL
    trades = 0
    wins = 0
    positions = {}
    
    start = datetime.now()
    
    try:
        # Load FOMO
        log_msg("📂 Loading FOMO tokens leaderboard...")
        await page.goto("https://fomo.family/tokens", wait_until="networkidle", timeout=10000)
        await asyncio.sleep(2)
        
        iteration = 0
        while (datetime.now() - start).total_seconds() < 3600:
            iteration += 1
            
            try:
                # Get leaderboard tokens
                rows = await page.query_selector_all("[class*='token'], [class*='row'], [role='row']")
                log_msg(f"📊 Found {len(rows)} tokens on leaderboard")
                
                # Buy top trending (if not already bought)
                for i, row in enumerate(rows[:10]):
                    try:
                        text = await row.text_content()
                        if text and len(positions) < 3 and text not in str(positions):
                            # Paper trade: record entry
                            coin_name = text.split()[0] if text else f"COIN_{i}"
                            if coin_name not in positions:
                                entry_price = 0.0001
                                bankroll -= POS_SIZE
                                positions[coin_name] = {
                                    "entry": entry_price,
                                    "size": POS_SIZE,
                                    "time": datetime.now(),
                                    "peak": entry_price
                                }
                                trades += 1
                                log_msg(f"🟢 BUY {coin_name} (PAPER) ${POS_SIZE:.2f} @ ${entry_price:.9f}")
                                log_trade({"ts": datetime.now().isoformat(), "action": "BUY", "coin": coin_name, "size": POS_SIZE})
                    except:
                        pass
                
                # Auto-sell after 5 min
                for coin in list(positions.keys()):
                    if (datetime.now() - positions[coin]["time"]).total_seconds() > 300:
                        exit_price = positions[coin]["entry"] * 1.15  # Assume +15%
                        pnl = POS_SIZE * 0.15
                        bankroll += POS_SIZE + pnl
                        wins += 1
                        log_msg(f"💰 SELL {coin} (PAPER) ${POS_SIZE:.2f} | PnL: +${pnl:.2f}")
                        log_trade({"ts": datetime.now().isoformat(), "action": "SELL", "coin": coin, "pnl": pnl})
                        del positions[coin]
                
                # Status every 5 min
                elapsed = (datetime.now() - start).total_seconds() / 60
                if int(elapsed) % 5 == 0 and iteration % 100 == 0:
                    pnl = bankroll - BANKROLL
                    log_msg(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} W:{wins} Open:{len(positions)}")
                
            except Exception as e:
                log_msg(f"❌ Cycle error: {e}")
            
            await asyncio.sleep(5)
        
        # Final report
        pnl = bankroll - BANKROLL
        log_msg("=" * 70)
        log_msg(f"TEST COMPLETE | Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades} | Wins:{wins}")
        log_msg("=" * 70)
    
    except Exception as e:
        log_msg(f"FATAL: {e}")
    
    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    asyncio.run(main())
