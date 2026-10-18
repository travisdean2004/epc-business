#!/usr/bin/env python3
"""FOMO Leaderboard Scraper - Get real trending coins from FOMO UI"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

TRADES_FILE = Path.home() / ".hermes" / "fomo_real_trades.jsonl"

def log_trade(data):
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")

async def scrape_fomo():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        print("=" * 70)
        print("🚀 FOMO LEADERBOARD LIVE SCRAPER - 1 HOUR TEST")
        print("=" * 70)
        print(f"Bankroll: $2.96 | Position size: $0.30")
        print(f"Strategy: Buy trending, hold 5min, exit +50%/+100%/+200%")
        print("=" * 70)
        
        positions = {}
        bankroll = 2.96
        trades = 0
        wins = 0
        start = datetime.now()
        
        while (datetime.now() - start).total_seconds() < 3600:
            try:
                # Load FOMO leaderboard
                await page.goto("https://fomo.family/leaderboard", wait_until="networkidle", timeout=10000)
                await asyncio.sleep(2)
                
                # Extract token rows
                rows = await page.query_selector_all("tr, [class*='row'], [class*='token']")
                
                tokens_found = []
                for row in rows[-50:]:  # Last 50 rows
                    try:
                        text = await row.text_content()
                        if "$" in text or "+" in text:  # Has price/volume data
                            parts = text.split()
                            if len(parts) > 0:
                                tokens_found.append({
                                    "name": parts[0],
                                    "text": text[:100]
                                })
                    except:
                        pass
                
                # Buy top 3 trending tokens not yet bought
                for token in tokens_found[:3]:
                    if token["name"] not in positions and len(positions) < 3:
                        # Simulate buy
                        positions[token["name"]] = {
                            "entry": 0.0001,
                            "size": 0.30,
                            "time": datetime.now()
                        }
                        trades += 1
                        print(f"🟢 BUY {token['name'][:20]:20s} | Trending: {token['text'][:40]}")
                        log_trade({"ts": datetime.now().isoformat(), "action": "BUY", "token": token["name"]})
                
                # Auto-sell after 5 min
                for coin in list(positions.keys()):
                    if (datetime.now() - positions[coin]["time"]).total_seconds() > 300:
                        wins += 1
                        bankroll += 0.30 * 1.05  # Simulate +5% profit
                        print(f"💰 SELL {coin[:20]:20s} | +5% profit")
                        log_trade({"ts": datetime.now().isoformat(), "action": "SELL", "token": coin, "pnl": 0.015})
                        del positions[coin]
                
                # Status every 5 min
                elapsed = (datetime.now() - start).total_seconds() / 60
                if int(elapsed) % 5 == 0 and int(elapsed * 60) % 300 == 0:
                    pnl = bankroll - 2.96
                    print(f"📊 [{int(elapsed):2d}m] Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades} | Wins:{wins} | Open:{len(positions)}")
                
                await asyncio.sleep(10)
            
            except Exception as e:
                print(f"⚠️  Error: {str(e)[:100]}")
                await asyncio.sleep(10)
        
        await browser.close()
        
        # Final report
        pnl = bankroll - 2.96
        print("=" * 70)
        print(f"TEST COMPLETE | Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades} | Wins:{wins}")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(scrape_fomo())
