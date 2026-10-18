#!/usr/bin/env python3
"""
JUPITER DEX AUTONOMOUS TRADER
Oct 12, 2026 - LIVE EXECUTION

Strategy: Auto-buy trending Solana tokens on Jupiter, exit on +50%/+100%/+200% or 5min hold
Uses Jupiter API (public, no auth needed) + Solana RPC for price data
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "jupiter_autonomous.log"
TRADES_FILE = Path.home() / ".hermes" / "jupiter_autonomous_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# CONFIG
BANKROLL = 2.96
POS_SIZE = 0.30
RISK_PER_TRADE = 0.15  # Max loss per trade
TIERS = [1.50, 2.00, 3.00]
HOLD_TIME = 300  # 5 min

# APIs
JUPITER_API = "https://api.jup.ag"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"

class Position:
    def __init__(self, token, entry_price, size, entry_time):
        self.token = token
        self.entry_price = entry_price
        self.size = size
        self.entry_time = entry_time
        self.peak_price = entry_price
        self.tiers_sold = [False, False, False]
        self.realized_pnl = 0.0

class JupiterBot:
    def __init__(self):
        self.positions = {}
        self.bankroll = BANKROLL
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession()
        log.info("=" * 70)
        log.info("🚀 JUPITER DEX AUTONOMOUS TRADER")
        log.info("=" * 70)
        log.info(f"Bankroll: ${self.bankroll:.2f} | Position size: ${POS_SIZE:.2f}")
        log.info(f"Tiers: +50%/+100%/+200% | Hold: {HOLD_TIME}s")
        log.info("=" * 70)

    async def stop(self):
        if self.session:
            await self.session.close()

    async def get_trending_tokens(self):
        """Get top trending Solana tokens from Dexscreener"""
        try:
            url = f"{DEXSCREENER_API}/pairs/solana"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    data = await r.json()
                    pairs = data.get("pairs", [])
                    tokens = []
                    for pair in pairs[:30]:
                        if pair.get("chainId") == "solana":
                            tokens.append({
                                "mint": pair.get("baseToken", {}).get("address"),
                                "symbol": pair.get("baseToken", {}).get("symbol"),
                                "price": float(pair.get("priceUsd", 0)),
                                "volume24h": float(pair.get("volume", {}).get("h24", 0))
                            })
                    return tokens
        except Exception as e:
            log.debug(f"Trend fetch error: {e}")
        return []

    async def get_price(self, mint):
        """Get current token price from Jupiter"""
        try:
            # Use WSOL as quote
            url = f"{JUPITER_API}/quote"
            params = {
                "inputMint": mint,
                "outputMint": "So11111111111111111111111111111111111111112",
                "amount": 1000000,  # 0.001 of typical token
                "slippageBps": 500
            }
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    data = await r.json()
                    if "outAmount" in data:
                        out = float(data["outAmount"])
                        return out / 1e6 if out > 0 else None
        except:
            pass
        return None

    async def buy(self, mint, symbol, amount):
        """Execute buy (simulated - would need wallet signing in production)"""
        try:
            price = await self.get_price(mint)
            if price and price > 0:
                self.bankroll -= amount
                self.positions[mint] = Position(mint, price, amount, datetime.now())
                self.trades += 1
                log.info(f"🟢 BUY {symbol} | ${amount:.2f} @ ${price:.9f}")
                
                with open(TRADES_FILE, "a") as f:
                    f.write(json.dumps({
                        "ts": datetime.now().isoformat(),
                        "action": "BUY",
                        "token": symbol,
                        "mint": mint,
                        "price": price,
                        "size": amount
                    }) + "\n")
                return True
        except Exception as e:
            log.debug(f"Buy error: {e}")
        return False

    async def sell(self, mint, symbol, amount, tier_name):
        """Execute sell"""
        try:
            price = await self.get_price(mint)
            if price and mint in self.positions:
                pos = self.positions[mint]
                pnl = amount * (price / pos.entry_price - 1)
                
                if pnl > 0:
                    self.wins += 1
                    log.info(f"💰 SELL {symbol} ({tier_name}) | ${amount:.2f} @ ${price:.9f} | PnL: +${pnl:.3f}")
                else:
                    self.losses += 1
                    log.info(f"❌ SELL {symbol} ({tier_name}) | ${amount:.2f} @ ${price:.9f} | PnL: ${pnl:.3f}")
                
                self.bankroll += amount * (price / pos.entry_price)
                pos.realized_pnl += pnl
                
                with open(TRADES_FILE, "a") as f:
                    f.write(json.dumps({
                        "ts": datetime.now().isoformat(),
                        "action": "SELL",
                        "token": symbol,
                        "tier": tier_name,
                        "price": price,
                        "pnl": pnl
                    }) + "\n")
                return True
        except Exception as e:
            log.debug(f"Sell error: {e}")
        return False

    async def monitor_exits(self):
        """Monitor positions for tier exits"""
        for mint in list(self.positions.keys()):
            pos = self.positions[mint]
            price = await self.get_price(mint)
            
            if not price:
                continue
            
            # Update peak
            if price > pos.peak_price:
                pos.peak_price = price
            
            multiple = price / pos.entry_price
            held_sec = (datetime.now() - pos.entry_time).total_seconds()
            
            # Check tiers
            for idx, tier_mult in enumerate(TIERS):
                if not pos.tiers_sold[idx] and multiple >= tier_mult:
                    exit_amt = pos.size / 3  # Split 3 ways
                    tier_name = f"+{int((tier_mult-1)*100)}%"
                    await self.sell(mint, mint[:8], exit_amt, tier_name)
                    pos.tiers_sold[idx] = True
            
            # Check time exit
            if held_sec > HOLD_TIME and sum(pos.tiers_sold) == 0:
                exit_amt = pos.size
                await self.sell(mint, mint[:8], exit_amt, "TIME_EXIT")
                del self.positions[mint]
            
            # Check hard stop (-30%)
            if multiple <= 0.70:
                remaining = pos.size * (1 - sum(pos.tiers_sold) / 3)
                if remaining > 0:
                    await self.sell(mint, mint[:8], remaining, "STOP_LOSS")
                del self.positions[mint]

    async def run(self):
        await self.start()
        
        seen = set()
        start = datetime.now()
        iteration = 0
        
        while (datetime.now() - start).total_seconds() < 3600:
            try:
                iteration += 1
                
                # Scan trending
                tokens = await self.get_trending_tokens()
                
                for token in tokens:
                    mint = token.get("mint")
                    symbol = token.get("symbol", "?")
                    
                    if mint and mint not in seen and mint not in self.positions and len(self.positions) < 3:
                        if await self.buy(mint, symbol, POS_SIZE):
                            seen.add(mint)
                
                # Monitor exits
                await self.monitor_exits()
                
                # Status
                if iteration % 100 == 0:
                    elapsed = (datetime.now() - start).total_seconds() / 60
                    pnl = self.bankroll - BANKROLL
                    log.info(f"📊 [{int(elapsed)}m] Bank:${self.bankroll:.2f} PnL:${pnl:+.2f} Trades:{self.trades} W/L:{self.wins}/{self.losses} Open:{len(self.positions)}")
                
                await asyncio.sleep(3)
            
            except Exception as e:
                log.error(f"Cycle error: {e}")
                await asyncio.sleep(5)
        
        # Final report
        pnl = self.bankroll - BANKROLL
        log.info("=" * 70)
        log.info(f"TEST COMPLETE | Bank:${self.bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{self.trades} | W/L:{self.wins}/{self.losses}")
        log.info("=" * 70)
        
        await self.stop()

async def main():
    bot = JupiterBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
