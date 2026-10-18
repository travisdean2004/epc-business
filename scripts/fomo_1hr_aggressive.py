#!/usr/bin/env python3
"""FOMO 1HR TEST - AGGRESSIVE ENTRY (Real FOMO prices)"""
import asyncio, json, logging, time
from datetime import datetime
from pathlib import Path
import aiohttp

LOG = Path.home() / ".hermes" / "fomo_1hr_test.log"
LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
log = logging.getLogger(__name__)

FOMO_API = "https://api.fomo.family"
BANKROLL = 2.96
START = datetime.now()

positions = {}
bankroll = BANKROLL
trades = 0
wins = 0

async def get_tokens():
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(f"{FOMO_API}/tokens/trending?limit=100", timeout=aiohttp.ClientTimeout(5)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("tokens", [])
        except: pass
    return []

async def get_chart(mint):
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(f"{FOMO_API}/tokens/{mint}/chart?interval=1m&limit=30", timeout=aiohttp.ClientTimeout(5)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("candles", [])
        except: pass
    return []

async def scan():
    global trades, bankroll
    tokens = await get_tokens()
    
    for t in tokens:
        mint = t.get("mint")
        mc = t.get("marketCap", 0)
        
        if mint in positions or mc >= 5_000_000:  # LOOSE: <$5M MC
            continue
        
        candles = await get_chart(mint)
        if len(candles) < 3:
            continue
        
        # AGGRESSIVE: Just 2%+ pump + any volume
        vol = candles[-1].get("volume", 0)
        avg_vol = sum(c.get("volume", 0) for c in candles[-10:-1]) / 9 if len(candles) >= 10 else 1
        pump = ((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"]) * 100
        
        if pump > 2.0 and (avg_vol == 0 or vol / avg_vol > 1.2):  # LOOSE: 2%+ pump, 1.2x vol
            entry = candles[-1]["close"]
            size = 0.25
            
            if bankroll >= size:
                bankroll -= size
                positions[mint] = {"entry": entry, "size": size, "tiers": [False, False, False]}
                trades += 1
                log.info(f"🟢 BUY: {mint[:8]}... ${size:.2f} @ ${entry:.9f}")

async def monitor():
    global bankroll, wins
    for mint in list(positions.keys()):
        candles = await get_chart(mint)
        if not candles:
            continue
        
        price = candles[-1]["close"]
        pos = positions[mint]
        mult = price / pos["entry"]
        
        tiers = [1.50, 2.00, 3.00]
        for i, t in enumerate(tiers):
            if mult >= t and not pos["tiers"][i]:
                amt = pos["size"] * 0.25
                pnl = amt * (mult - 1)
                bankroll += amt * mult
                wins += 1
                pos["tiers"][i] = True
                log.info(f"💰 SELL: {mint[:8]}... +{(mult-1)*100:.0f}% PnL: ${pnl:.3f}")
        
        if all(pos["tiers"]):
            del positions[mint]

async def main():
    log.info("🧪 1HR TEST - AGGRESSIVE (Real FOMO prices)")
    log.info(f"Start: {START} | Duration: 60 min")
    
    while True:
        await scan()
        await monitor()
        
        elapsed = (datetime.now() - START).total_seconds() / 60
        if elapsed % 5 < 0.1:  # Every 5 min
            log.info(f"📊 [{elapsed:.0f}min] Bankroll: ${bankroll:.3f} | Trades: {trades} | Wins: {wins} | Open: {len(positions)}")
        
        if elapsed > 60:
            pnl = bankroll - BANKROLL
            log.info(f"✅ TEST COMPLETE | Final: ${bankroll:.3f} | PnL: ${pnl:+.3f} ({pnl/BANKROLL*100:+.0f}%)")
            break
        
        await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
