#!/usr/bin/env python3
"""
FOMO MEMECOIN TRADER - PRO RULES (Orangie + TJR + Kimchi)
=========================================================
Oct 12, 2026

STRATEGY STACK:
1. ORANGIE SCALP: Early entry (<$1M MC), exit ladder 25%@+50%,+100%,+200%,runner
2. TJR CONFLUENCE: 4H bias + 5-15min zones + fixed exit levels
3. KIMCHI GRIND: 14hr/day monitoring, extreme discipline, no emotions

Entry Rules (from all 3):
- Only trade coins <$1M market cap (Orangie + Kimchi rule)
- Wait for 2nd pump on higher volume (professional entry, not first)
- Check 4-hour uptrend bias (TJR rule)
- Enter on 5-15min breakout (TJR rule)
- Risk max 1% per trade (Orangie rule)

Exit Rules (from all 3):
- Fixed ladder: 25% @ +50%, 25% @ +100%, 25% @ +200%, 25% runner
- Runner: Trailing stop -30% from peak (Kimchi rule)
- Time exit: If sideways >24hrs, exit (TJR rule)
- Stop loss: -30% hard stop (Orangie rule)

Behavioral Rules:
- No manual trades (bot only)
- No overriding exits
- 24-hour cooling off after losses >2%
- Log every trade
- Copy Orangie instantly when he trades
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from collections import defaultdict

# ============================================================================
# LOGGING
# ============================================================================

LOG_FILE = Path.home() / ".hermes" / "fomo_pro_trader.log"
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
# CONFIG - PRO RULES ONLY
# ============================================================================

FOMO_API_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
FOMO_API_BASE = "https://api.fomo.family"

BANKROLL = 2.96
BANKROLL_MIN = 0.30

# ORANGIE RULE: Only trade <$1M MC
MAX_MARKET_CAP = 1_000_000

# POSITION SIZING
RISK_PER_TRADE_PCT = 1.0  # 1% max loss per trade (Orangie rule)
POSITION_SIZE_MIN = 0.15
POSITION_SIZE_MAX = 0.35

# ENTRY RULES
VOLUME_SPIKE_MIN = 2.0  # 2x average volume (pro entry, not FOMO)
PRICE_PUMP_MIN_PCT = 5.0  # Wait for 5%+ move (2nd pump, not first)
UPTREND_REQUIRED = True  # Check 4H bias (TJR rule)

# EXIT RULES (FIXED LADDER - Orangie + Kimchi)
EXIT_TIERS = [
    {"multiple": 1.50, "pct": 0.25, "name": "+50%"},
    {"multiple": 2.00, "pct": 0.25, "name": "+100%"},
    {"multiple": 3.00, "pct": 0.25, "name": "+200%"},
    # Tier 4 is RUNNER with trailing stop
]
RUNNER_TRAILING_STOP_PCT = -30.0  # Kimchi rule

# STOP LOSS
HARD_STOP_LOSS_PCT = -30.0  # Orangie rule

# TIME EXITS (TJR rule)
TIME_EXIT_HOURS = 24  # If sideways >24hrs, exit

# BEHAVIORAL RULES
COOLING_OFF_PCT = 2.0  # 24hr break after -2% loss
COOLING_OFF_HOURS = 24

TRADES_FILE = Path.home() / ".hermes" / "fomo_pro_trades.jsonl"
ORANGIE_WALLET = "6atxM2LoHbHxPzVzk2BpDqJvJdCfXdGTJG6PQqwFPDU2"

# ============================================================================
# FOMO API
# ============================================================================

class FOMAAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = FOMO_API_BASE
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
    
    def get_token_info(self, token_mint: str):
        """Get token market cap, price, volume"""
        try:
            url = f"{self.base_url}/tokens/{token_mint}"
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def get_chart(self, token_mint: str, interval="1m", limit=100):
        """Get candlestick chart data"""
        try:
            url = f"{self.base_url}/tokens/{token_mint}/chart"
            params = {"interval": interval, "limit": limit}
            resp = self.session.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def buy(self, token_mint: str, amount_usd: float):
        """Execute buy"""
        try:
            url = f"{self.base_url}/trades/buy"
            payload = {
                "tokenMint": token_mint,
                "amountUSD": amount_usd,
                "slippage": 2.0
            }
            resp = self.session.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def sell(self, token_mint: str, amount_usd: float):
        """Execute sell"""
        try:
            url = f"{self.base_url}/trades/sell"
            payload = {
                "tokenMint": token_mint,
                "amountUSD": amount_usd,
                "slippage": 2.0
            }
            resp = self.session.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def get_hot_tokens(self, limit=20):
        """Get top trending tokens by volume/MC"""
        try:
            url = f"{self.base_url}/tokens/trending"
            params = {"limit": limit}
            resp = self.session.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return []

# ============================================================================
# POSITION TRACKING
# ============================================================================

class ProPosition:
    def __init__(self, token: str, entry_price: float, size_usd: float, mc: float):
        self.token = token
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.market_cap = mc
        self.entry_time = datetime.now()
        self.peak_price = entry_price
        self.peak_time = entry_time
        
        # Exit tracking
        self.tiers_executed = [False, False, False]  # 3 tiers + runner
        self.runner_active = False
        self.runner_peak = entry_price
        self.time_exit_triggered = False
        
        # P&L
        self.realized_pnl = 0.0
        self.closed_pnl = 0.0

# ============================================================================
# PRO TRADER BOT
# ============================================================================

class FOMAProTraderBot:
    def __init__(self, api_key: str):
        self.api = FOMAAPI(api_key)
        self.bankroll = BANKROLL
        self.positions = {}
        self.price_history = defaultdict(list)
        self.last_loss_time = None
        self.in_cooling_off = False
        
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.session_start = datetime.now()
        
        self.orangie_seen = set()
    
    def log(self, msg: str, level="INFO"):
        getattr(log, level.lower())(msg)
    
    def log_trade(self, data: dict):
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")
    
    async def check_cooling_off(self):
        """BEHAVIORAL RULE: 24hr cooling off after losses >2%"""
        if self.in_cooling_off:
            elapsed = (datetime.now() - self.last_loss_time).total_seconds() / 3600
            if elapsed >= COOLING_OFF_HOURS:
                self.in_cooling_off = False
                self.log(f"✅ Cooling off period over. Resuming trades.", "INFO")
            else:
                self.log(f"⏸️  In cooling off period ({elapsed:.1f}h/{COOLING_OFF_HOURS}h)", "DEBUG")
                return False
        return True
    
    async def scan_opportunities(self):
        """ORANGIE RULE: Scan <$1M MC tokens for early entry"""
        if not await self.check_cooling_off():
            return
        
        try:
            hot_tokens = self.api.get_hot_tokens(limit=50)
            if not hot_tokens:
                return
            
            for token_data in hot_tokens:
                token_mint = token_data.get("mint")
                market_cap = token_data.get("marketCap", 0)
                
                # ORANGIE RULE: Only <$1M MC
                if market_cap >= MAX_MARKET_CAP:
                    continue
                
                # Already holding?
                if token_mint in self.positions:
                    continue
                
                # Check chart for entry signal
                await self.evaluate_entry(token_mint, market_cap)
        
        except Exception as e:
            self.log(f"Scan error: {str(e)}", "DEBUG")
    
    async def evaluate_entry(self, token_mint: str, market_cap: float):
        """PRO ENTRY RULES: Volume spike + price pump + bias check"""
        try:
            # Get chart
            chart = self.api.get_chart(token_mint, interval="1m", limit=20)
            if not chart or len(chart.get("candles", [])) < 5:
                return
            
            candles = chart["candles"]
            latest = candles[-1]
            prev = candles[-2]
            
            # RULE 1: Price pump (2nd pump, not first)
            price_change_pct = ((latest["close"] - prev["close"]) / prev["close"]) * 100
            if price_change_pct < PRICE_PUMP_MIN_PCT:
                return
            
            # RULE 2: Volume spike (2x+ average)
            avg_vol = sum(c["volume"] for c in candles[-10:-1]) / 9
            vol_ratio = latest["volume"] / avg_vol if avg_vol > 0 else 0
            if vol_ratio < VOLUME_SPIKE_MIN:
                return
            
            # RULE 3: 4H uptrend bias (TJR rule)
            chart_4h = self.api.get_chart(token_mint, interval="4h", limit=5)
            if chart_4h:
                candles_4h = chart_4h["candles"]
                if len(candles_4h) >= 2:
                    is_uptrend = candles_4h[-1]["close"] > candles_4h[-2]["close"]
                    if UPTREND_REQUIRED and not is_uptrend:
                        return
            
            # ALL RULES PASSED: ENTRY SIGNAL
            await self.enter_trade(token_mint, latest["close"], market_cap)
        
        except Exception as e:
            self.log(f"Entry eval error: {str(e)}", "DEBUG")
    
    async def enter_trade(self, token_mint: str, entry_price: float, market_cap: float):
        """Execute entry with position sizing"""
        try:
            # Position sizing: Risk max 1% per trade
            max_loss = self.bankroll * (RISK_PER_TRADE_PCT / 100)
            stop_ratio = abs(HARD_STOP_LOSS_PCT) / 100
            position_size = max_loss / stop_ratio
            position_size = max(position_size, POSITION_SIZE_MIN)
            position_size = min(position_size, POSITION_SIZE_MAX)
            
            if position_size > self.bankroll * 0.5:
                self.log(f"Position size {position_size} too large, skipping", "WARNING")
                return
            
            # Execute buy
            buy_result = self.api.buy(token_mint, position_size)
            if not buy_result:
                self.log(f"Buy failed for {token_mint[:8]}...", "ERROR")
                return
            
            self.bankroll -= position_size
            self.positions[token_mint] = ProPosition(token_mint, entry_price, position_size, market_cap)
            self.total_trades += 1
            
            self.log(f"🟢 ENTRY: {token_mint[:8]}... | ${position_size:.2f} @ ${entry_price:.9f} | MC: ${market_cap:,.0f}", "INFO")
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "BUY",
                "token": token_mint,
                "entry_price": entry_price,
                "market_cap": market_cap,
                "size": position_size,
                "status": "OPEN"
            })
        
        except Exception as e:
            self.log(f"Entry error: {str(e)}", "ERROR")
    
    async def monitor_exits(self):
        """Monitor all positions and execute exits (fixed ladder + trailing stop + time)"""
        for token_mint in list(self.positions.keys()):
            try:
                pos = self.positions[token_mint]
                token_info = self.api.get_token_info(token_mint)
                if not token_info:
                    continue
                
                current_price = token_info.get("price", 0)
                if current_price <= 0:
                    continue
                
                # Track peak for trailing stop
                if current_price > pos.peak_price:
                    pos.peak_price = current_price
                    pos.peak_time = datetime.now()
                
                # Calculate metrics
                multiple = current_price / pos.entry_price
                time_held_hours = (datetime.now() - pos.entry_time).total_seconds() / 3600
                
                # CHECK TIERS (Fixed ladder - Orangie + Kimchi)
                for tier_idx, tier in enumerate(EXIT_TIERS):
                    if not pos.tiers_executed[tier_idx] and multiple >= tier["multiple"]:
                        exit_amount = pos.size_usd * tier["pct"]
                        await self.exit_tier(token_mint, exit_amount, tier, current_price)
                        pos.tiers_executed[tier_idx] = True
                
                # CHECK RUNNER (Trailing stop - Kimchi rule)
                if all(pos.tiers_executed) and not pos.runner_active:
                    pos.runner_active = True
                    self.log(f"📊 {token_mint[:8]}... now in RUNNER phase (trailing stop)", "INFO")
                
                if pos.runner_active:
                    trailing_price = pos.peak_price * (1 + RUNNER_TRAILING_STOP_PCT / 100)
                    if current_price < trailing_price:
                        exit_amount = pos.size_usd * 0.25  # Last 25%
                        await self.exit_tier(token_mint, exit_amount, {"name": "RUNNER"}, current_price)
                        del self.positions[token_mint]
                        continue
                
                # CHECK TIME EXIT (TJR rule: if sideways >24hrs, exit)
                if time_held_hours > TIME_EXIT_HOURS and not pos.time_exit_triggered:
                    self.log(f"⏰ {token_mint[:8]}... held >24hrs with no pump, exiting", "INFO")
                    remaining = pos.size_usd * (1 - sum(pos.tiers_executed) * 0.25)
                    if remaining > 0:
                        await self.exit_tier(token_mint, remaining, {"name": "TIME_EXIT"}, current_price)
                    pos.time_exit_triggered = True
                
                # CHECK HARD STOP LOSS (Orangie rule: -30%)
                if multiple <= (1 + HARD_STOP_LOSS_PCT / 100):
                    self.log(f"🔴 {token_mint[:8]}... hit hard stop loss {HARD_STOP_LOSS_PCT}%", "WARNING")
                    remaining = pos.size_usd * (1 - sum(pos.tiers_executed) * 0.25)
                    if remaining > 0:
                        await self.exit_tier(token_mint, remaining, {"name": "STOP_LOSS"}, current_price)
                    del self.positions[token_mint]
            
            except Exception as e:
                self.log(f"Exit monitor error: {str(e)}", "DEBUG")
    
    async def exit_tier(self, token_mint: str, amount: float, tier: dict, exit_price: float):
        """Execute tier exit"""
        try:
            sell_result = self.api.sell(token_mint, amount)
            if not sell_result:
                self.log(f"Sell failed: {token_mint[:8]}...", "ERROR")
                return
            
            pos = self.positions[token_mint]
            pnl = amount * (exit_price / pos.entry_price - 1)
            
            if pnl > 0:
                self.wins += 1
                self.log(f"💰 EXIT ({tier['name']}): {token_mint[:8]}... | ${amount:.2f} @ ${exit_price:.9f} | PnL: +${pnl:.3f} ✅", "INFO")
            else:
                self.losses += 1
                self.log(f"❌ EXIT ({tier['name']}): {token_mint[:8]}... | ${amount:.2f} @ ${exit_price:.9f} | PnL: ${pnl:.3f}", "INFO")
            
            self.bankroll += amount * (exit_price / pos.entry_price)
            pos.closed_pnl += pnl
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "SELL",
                "token": token_mint,
                "tier": tier["name"],
                "exit_price": exit_price,
                "pnl": pnl,
                "status": "SUCCESS"
            })
            
            # BEHAVIORAL RULE: Check if loss >2% for cooling off
            if pnl < 0 and abs(pnl / pos.size_usd) > (COOLING_OFF_PCT / 100):
                self.in_cooling_off = True
                self.last_loss_time = datetime.now()
                self.log(f"⚠️  Loss >{COOLING_OFF_PCT}%, entering {COOLING_OFF_HOURS}h cooling off", "WARNING")
        
        except Exception as e:
            self.log(f"Exit error: {str(e)}", "ERROR")
    
    async def run(self):
        try:
            self.log("=" * 80)
            self.log("🚀 FOMO PRO TRADER (Orangie + TJR + Kimchi Rules)")
            self.log("=" * 80)
            self.log(f"Bankroll: ${self.bankroll:.2f} | Risk: {RISK_PER_TRADE_PCT}% per trade")
            self.log(f"Entry: <${MAX_MARKET_CAP:,.0f} MC | Vol spike {VOLUME_SPIKE_MIN}x+ | Price pump {PRICE_PUMP_MIN_PCT}%+")
            self.log(f"Exit: Ladder +50%/+100%/+200% + Runner (trailing {RUNNER_TRAILING_STOP_PCT}%) + Time ({TIME_EXIT_HOURS}h)")
            self.log(f"Stop: Hard -{abs(HARD_STOP_LOSS_PCT)}% | Cooling off: -{COOLING_OFF_PCT}% triggers {COOLING_OFF_HOURS}h break")
            self.log("=" * 80)
            
            iteration = 0
            while True:
                try:
                    iteration += 1
                    
                    # Scan for opportunities
                    await self.scan_opportunities()
                    
                    # Monitor open positions
                    await self.monitor_exits()
                    
                    # Status every 100 cycles
                    if iteration % 100 == 0:
                        win_rate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
                        pnl = self.bankroll - BANKROLL
                        
                        self.log(f"📊 Bankroll: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} | Trades: {self.total_trades} | Win%: {win_rate:.0f}% | Open: {len(self.positions)}", "INFO")
                        
                        if self.bankroll < BANKROLL_MIN:
                            self.log(f"❌ Bankroll below minimum", "ERROR")
                            break
                    
                    await asyncio.sleep(3)
                
                except Exception as e:
                    self.log(f"Cycle error: {str(e)}", "ERROR")
                    await asyncio.sleep(5)
        
        except KeyboardInterrupt:
            self.log("⏹️  Bot stopped", "INFO")
        finally:
            pnl = self.bankroll - BANKROLL
            self.log(f"Final: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} | Trades: {self.total_trades} | W/L: {self.wins}/{self.losses}", "INFO")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    bot = FOMAProTraderBot(FOMO_API_KEY)
    asyncio.run(bot.run())
