#!/usr/bin/env python3
"""
FOMO BOT - 1 HOUR TEST (Paper Trading Real Coins)
Oct 12, 2026
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
import aiohttp

LOG_FILE = Path.home() / ".hermes" / "fomo_test_1hr.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_test_1hr_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

SESSION_TOKEN = open(Path.home() / ".hermes" / "fomo_session.txt").read().strip()
API_BASE = "https://api.fomo.family"

CONFIG = {
    "bankroll": 2.96,
    "position_size": 0.25,
    "test_duration_minutes": 60,
    "tiers": [
        {"multiple": 1.50, "pct": 0.25, "name": "+50%"},
        {"multiple": 2.00, "pct": 0.25, "name": "+100%"},
        {"multiple": 3.00, "pct": 0.25, "name": "+200%"},
    ]
}

class Position:
    def __init__(self, coin, entry_price, size):
        self.coin = coin
        self.entry_price = entry_price
        self.size = size
        self.peak_price = entry_price
        self.tiers_sold = [False, False, False]
        self.entry_time = datetime.now()
        self.realized_pnl = 0.0

class FOMATestBot:
    def __init__(self):
        self.positions = {}
        self.bankroll = CONFIG["bankroll"]
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.start_time = datetime.now()
        self.session = None

    def log(self, msg, level="INFO"):
        getattr(log, level.lower())(msg)

    def log_trade(self, data):
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")

    async def get_tokens(self):
        """Fetch trending tokens"""
        try:
            async with self.session.get(f"{API_BASE}/tokens/trending", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("tokens", [])
        except:
            pass
        return []

    async def get_price(self, token_mint):
        """Get current token price"""
        try:
            async with self.session.get(f"{API_BASE}/tokens/{token_mint}", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("price", 0)
        except:
            pass
        return 0

    async def scan_and_trade(self):
        """Scan tokens and paper trade"""
        tokens = await self.get_tokens()
        
        for token in tokens[:20]:
            mint = token.get("mint")
            mc = token.get("marketCap", 0)
            
            if mint in self.positions or mc >= 2_000_000:
                continue
            
            if self.bankroll < CONFIG["position_size"]:
                break
            
            # Paper entry
            entry_price = token.get("price", 0.0001)
            if entry_price > 0:
                self.bankroll -= CONFIG["position_size"]
                self.positions[mint] = Position(mint, entry_price, CONFIG["position_size"])
                self.total_trades += 1
                
                self.log(f"📝 PAPER BUY: {mint[:8]}... | ${CONFIG['position_size']:.2f} @ ${entry_price:.9f}", "INFO")
                self.log_trade({
                    "timestamp": datetime.now().isoformat(),
                    "action": "BUY",
                    "coin": mint,
                    "entry_price": entry_price,
                    "mode": "PAPER"
                })

    async def monitor_exits(self):
        """Check positions against real prices"""
        for mint in list(self.positions.keys()):
            pos = self.positions[mint]
            price = await self.get_price(mint)
            
            if price <= 0:
                continue
            
            if price > pos.peak_price:
                pos.peak_price = price
            
            multiple = price / pos.entry_price
            
            for idx, tier in enumerate(CONFIG["tiers"]):
                if not pos.tiers_sold[idx] and multiple >= tier["multiple"]:
                    exit_amt = pos.size * tier["pct"]
                    pnl = exit_amt * (price / pos.entry_price - 1)
                    
                    if pnl > 0:
                        self.wins += 1
                    else:
                        self.losses += 1
                    
                    self.bankroll += exit_amt * (price / pos.entry_price)
                    pos.realized_pnl += pnl
                    pos.tiers_sold[idx] = True
                    
                    status = "✅" if pnl > 0 else "❌"
                    self.log(f"💰 PAPER SELL ({tier['name']}): {mint[:8]}... | PnL: ${pnl:+.3f} {status}", "INFO")
                    self.log_trade({
                        "timestamp": datetime.now().isoformat(),
                        "action": "SELL",
                        "coin": mint,
                        "tier": tier["name"],
                        "pnl": pnl,
                        "mode": "PAPER"
                    })
            
            if multiple <= 0.70:  # -30% hard stop
                remaining = pos.size * (1 - sum([1 for x in pos.tiers_sold if x]) * 0.25)
                if remaining > 0:
                    pnl = remaining * (price / pos.entry_price - 1)
                    self.bankroll += remaining * (price / pos.entry_price)
                    pos.realized_pnl += pnl
                    self.losses += 1
                    self.log(f"🔴 PAPER STOP: {mint[:8]}... | PnL: ${pnl:+.3f}", "INFO")
                del self.positions[mint]

    async def run(self):
        self.session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {SESSION_TOKEN}"})
        
        self.log("=" * 80)
        self.log("🧪 1-HOUR TEST (Paper Trading Real FOMO Coins)")
        self.log("=" * 80)
        self.log(f"Start bankroll: ${self.bankroll:.2f} (PAPER)")
        self.log(f"Position size: ${CONFIG['position_size']:.2f}")
        self.log(f"Test duration: {CONFIG['test_duration_minutes']} minutes")
        self.log("=" * 80)
        
        iteration = 0
        while True:
            elapsed = (datetime.now() - self.start_time).total_seconds() / 60
            
            if elapsed > CONFIG["test_duration_minutes"]:
                break
            
            iteration += 1
            await self.scan_and_trade()
            await self.monitor_exits()
            
            if iteration % 20 == 0:
                pnl = self.bankroll - CONFIG["bankroll"]
                wr = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
                self.log(f"📊 [{elapsed:.0f}min] Bankroll: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} | Trades: {self.total_trades} | W/L: {self.wins}/{self.losses} | WR: {wr:.0f}% | Open: {len(self.positions)}", "INFO")
            
            await asyncio.sleep(3)
        
        await self.session.close()
        
        pnl = self.bankroll - CONFIG["bankroll"]
        wr = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
        
        self.log("=" * 80)
        self.log(f"TEST COMPLETE")
        self.log(f"Final bankroll: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} ({(pnl/CONFIG['bankroll']*100):+.1f}%)")
        self.log(f"Trades: {self.total_trades} | W/L: {self.wins}/{self.losses} | Win rate: {wr:.0f}%")
        self.log("=" * 80)

async def main():
    bot = FOMATestBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
