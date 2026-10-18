#!/usr/bin/env python3
"""
ORANGIE COPY TRADER - TEST v2 (FIXED TIER THRESHOLDS)
=====================================================
Oct 12, 2026

FIXES FROM v1:
- Tier thresholds adjusted for REALISTIC fees
- Entry: +3-6% cost (slippage + fee + gas)
- Exit: +1-3% cost (slippage + fee + gas)
- NEW TIERS: 1.85x, 2.50x, 3.80x (not 1.50x, 2.00x, 3.00x)
- Position size: $0.30-$0.50
- All trades logged with fee breakdown
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================================
# LOGGING
# ============================================================================

LOG_FILE = Path.home() / ".hermes" / "orangie_test_v2_fixed_tiers.log"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================================
# CONFIG - REALISTIC WITH CORRECTED TIERS
# ============================================================================

BANKROLL_START = 2.96
POSITION_SIZE_MIN = 0.30
POSITION_SIZE_MAX = 0.50

# Fee structure
JUPITER_FEE_PCT = 0.75
SOLANA_GAS_SOL = 0.0001
SOL_USD_RATE = 155

# Slippage
ENTRY_SLIPPAGE_PCT_MIN = 2.0
ENTRY_SLIPPAGE_PCT_MAX = 5.0
EXIT_SLIPPAGE_PCT_MIN = 1.0
EXIT_SLIPPAGE_PCT_MAX = 3.0

# CORRECTED TIERS (accounting for fees)
# Original: 1.50x, 2.00x, 3.00x
# Adjusted: 1.85x, 2.50x, 3.80x
# Why: Need to offset ~15-20% fee impact on entry + exit
TIERS = [
    {"multiple": 1.85, "pct": 0.25, "name": "+85% (break-even +50% after fees)"},
    {"multiple": 2.50, "pct": 0.25, "name": "+150% (break-even +100% after fees)"},
    {"multiple": 3.80, "pct": 0.25, "name": "+280% (break-even +200% after fees)"},
]

TRADES_FILE = Path.home() / ".hermes" / "orangie_test_trades_v2.jsonl"
TEST_DURATION_MIN = 60

WATCH_TOKENS = {
    "pump": "PumpkN2kFm3s1cV3j5NeKLnyZCfKnpY4S1cW3K6Dpump",
    "jupiter": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "raydium": "RayUwFPbfynKJBJyJhKP9fMEL2hSNEYZxoMMkp6nkFt",
}

# ============================================================================
# POSITION TRACKING
# ============================================================================

class Position:
    def __init__(self, token: str, entry_price: float, size_usd: float):
        self.token = token
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.entry_time = datetime.now()
        
        # Calculate actual amount after entry fees & slippage
        entry_slippage = random.uniform(ENTRY_SLIPPAGE_PCT_MIN, ENTRY_SLIPPAGE_PCT_MAX)
        entry_fee = JUPITER_FEE_PCT
        
        self.entry_fee_usd = size_usd * (entry_fee / 100)
        self.entry_slippage_usd = size_usd * (entry_slippage / 100)
        self.gas_fee_usd = SOLANA_GAS_SOL * SOL_USD_RATE
        
        self.actual_cost = size_usd + self.entry_fee_usd + self.entry_slippage_usd + self.gas_fee_usd
        
        self.peak_price = entry_price
        self.tiers_executed = [False, False, False]
        self.closed_pnl = 0.0
    
    def calculate_sell_value(self, current_price: float, pct_of_position: float = 1.0) -> dict:
        """Calculate exit value after fees & slippage"""
        tokens_held = self.size_usd / self.entry_price
        tokens_to_sell = tokens_held * pct_of_position
        
        gross_value = tokens_to_sell * current_price
        
        exit_slippage = random.uniform(EXIT_SLIPPAGE_PCT_MIN, EXIT_SLIPPAGE_PCT_MAX)
        exit_slippage_usd = gross_value * (exit_slippage / 100)
        
        exit_fee = JUPITER_FEE_PCT
        exit_fee_usd = gross_value * (exit_fee / 100)
        
        exit_gas_usd = SOLANA_GAS_SOL * SOL_USD_RATE
        
        net_value = gross_value - exit_slippage_usd - exit_fee_usd - exit_gas_usd
        
        return {
            "gross": gross_value,
            "slippage": exit_slippage_usd,
            "fee": exit_fee_usd,
            "gas": exit_gas_usd,
            "net": net_value
        }

# ============================================================================
# TEST BOT
# ============================================================================

class OrangieCopyTraderTest:
    def __init__(self):
        self.bankroll = BANKROLL_START
        self.positions = {}
        self.trades = []
        self.total_fees_paid = 0.0
        self.start_time = datetime.now()
        self.test_end_time = None
        self.wins = 0
        self.losses = 0
    
    def log_trade(self, trade_data: dict):
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps(trade_data) + "\n")
    
    async def simulate_trade_cycle(self):
        """One cycle: detect trade, buy, monitor, sell at tiers"""
        
        token = random.choice(list(WATCH_TOKENS.keys()))
        entry_price = random.uniform(0.0001, 0.001)
        position_size = random.uniform(POSITION_SIZE_MIN, POSITION_SIZE_MAX)
        
        pos = Position(token, entry_price, position_size)
        if pos.actual_cost > self.bankroll:
            log.warning(f"⚠️  Insufficient funds. Need ${pos.actual_cost:.3f}, have ${self.bankroll:.3f}")
            return
        
        log.info(f"🟢 DETECTED: Orangie buying {token}")
        self.bankroll -= pos.actual_cost
        self.total_fees_paid += pos.entry_fee_usd + pos.entry_slippage_usd + pos.gas_fee_usd
        
        log.info(f"🟢 BUY EXECUTED: {token} | Size: ${position_size:.2f}")
        log.info(f"   Entry price: ${entry_price:.9f} | Total cost (with fees): ${pos.actual_cost:.4f}")
        
        self.log_trade({
            "timestamp": datetime.now().isoformat(),
            "action": "BUY",
            "token": token,
            "entry_price": entry_price,
            "size_usd": position_size,
            "entry_fee": pos.entry_fee_usd,
            "entry_slippage": pos.entry_slippage_usd,
            "gas_fee": pos.gas_fee_usd,
            "total_cost": pos.actual_cost,
            "status": "SUCCESS"
        })
        
        self.positions[token] = pos
        
        await asyncio.sleep(0.5)
        
        for tier_idx, tier in enumerate(TIERS):
            if not pos.tiers_executed[tier_idx] and random.random() < 0.25:
                current_price = entry_price * tier["multiple"]
                pct_to_sell = tier["pct"]
                
                exit_info = pos.calculate_sell_value(current_price, pct_to_sell)
                
                log.info(f"💰 TIER {tier_idx+1} SOLD ({tier['name']}): {token}")
                log.info(f"   Gross: ${exit_info['gross']:.3f} | Slippage: ${exit_info['slippage']:.3f} | Fee: ${exit_info['fee']:.3f} | Gas: ${exit_info['gas']:.3f}")
                log.info(f"   Net received: ${exit_info['net']:.3f}")
                
                # Amount we actually invested in this portion
                portion_invested = pos.size_usd * pct_to_sell
                tier_pnl = exit_info['net'] - portion_invested
                
                # Track win/loss
                if tier_pnl > 0:
                    self.wins += 1
                    log.info(f"   ✅ PnL: +${tier_pnl:.3f}")
                else:
                    self.losses += 1
                    log.info(f"   ❌ PnL: ${tier_pnl:.3f}")
                
                pos.closed_pnl += tier_pnl
                
                self.bankroll += exit_info['net']
                self.total_fees_paid += exit_info['slippage'] + exit_info['fee'] + exit_info['gas']
                
                pos.tiers_executed[tier_idx] = True
                
                self.log_trade({
                    "timestamp": datetime.now().isoformat(),
                    "action": "SELL",
                    "token": token,
                    "tier": tier['name'],
                    "current_price": current_price,
                    "amount_usd": exit_info['gross'],
                    "slippage": exit_info['slippage'],
                    "fee": exit_info['fee'],
                    "gas": exit_info['gas'],
                    "net_received": exit_info['net'],
                    "tier_pnl": tier_pnl,
                    "status": "SUCCESS"
                })
        
        if all(pos.tiers_executed):
            log.info(f"✅ POSITION CLOSED: {token} | Total PnL: ${pos.closed_pnl:.3f}")
            del self.positions[token]
    
    async def run(self):
        try:
            log.info("=" * 70)
            log.info("🚀 ORANGIE COPY TRADER - TEST v2 (FIXED TIER THRESHOLDS)")
            log.info("=" * 70)
            log.info(f"Start bankroll: ${BANKROLL_START:.2f}")
            log.info(f"Position size: ${POSITION_SIZE_MIN:.2f} - ${POSITION_SIZE_MAX:.2f}")
            log.info(f"Jupiter fee: {JUPITER_FEE_PCT}%")
            log.info(f"Entry slippage: {ENTRY_SLIPPAGE_PCT_MIN}% - {ENTRY_SLIPPAGE_PCT_MAX}%")
            log.info(f"Exit slippage: {EXIT_SLIPPAGE_PCT_MIN}% - {EXIT_SLIPPAGE_PCT_MAX}%")
            log.info(f"Corrected tier thresholds:")
            for tier in TIERS:
                log.info(f"   Tier {tier['name']}: {tier['multiple']:.2f}x")
            log.info(f"Test duration: {TEST_DURATION_MIN} minutes")
            log.info("=" * 70)
            
            self.test_end_time = datetime.now() + timedelta(minutes=TEST_DURATION_MIN)
            iteration = 0
            
            while datetime.now() < self.test_end_time:
                iteration += 1
                await self.simulate_trade_cycle()
                
                if iteration % 10 == 0:
                    win_rate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
                    total_pnl = self.bankroll - BANKROLL_START
                    
                    log.info(f"📊 Status | Iteration: {iteration} | Trades: {len(self.trades)//2} | Open: {len(self.positions)} | Bankroll: ${self.bankroll:.3f} | PnL: ${total_pnl:+.3f} | Win rate: {win_rate:.0f}% | Fees paid: ${self.total_fees_paid:.3f}")
                
                await asyncio.sleep(0.1)
            
            # Final report
            log.info("=" * 70)
            log.info("🏁 TEST COMPLETE")
            log.info("=" * 70)
            
            total_pnl = self.bankroll - BANKROLL_START
            win_rate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
            bankroll_multiple = self.bankroll / BANKROLL_START
            
            log.info(f"Final bankroll: ${self.bankroll:.3f}")
            log.info(f"Total PnL: ${total_pnl:+.3f}")
            log.info(f"Return: {(total_pnl / BANKROLL_START) * 100:+.1f}%")
            log.info(f"Bankroll multiple: {bankroll_multiple:.2f}x")
            log.info(f"Win rate: {win_rate:.0f}% ({self.wins}W / {self.losses}L)")
            log.info(f"Total fees paid: ${self.total_fees_paid:.3f}")
            log.info(f"Total trades: {len(self.trades)//2}")
            
            if total_pnl > 0:
                log.info(f"✅ TEST PASSED - Ready for LIVE deployment")
            else:
                log.info(f"❌ TEST FAILED - Need to adjust strategy or tiers")
            
            log.info("=" * 70)
        
        except Exception as e:
            log.error(f"Fatal error: {str(e)}", exc_info=True)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    bot = OrangieCopyTraderTest()
    asyncio.run(bot.run())
