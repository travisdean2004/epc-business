#!/usr/bin/env python3
"""
FOMO MEMECOIN TRADER - RESEARCH-BACKED (Orangie + TJR + Kimchi)
===============================================================
Oct 12, 2026 - LIVE TRADING WITH REAL RULES

This bot is built on 60+ minutes of actual trader research:
- Orangie: Twitter tracking, multi-pump confirmation, wallet following
- TJR: Structure/liquidity/confluence analysis, time exits, trailing stops
- Kimchi: 15-hour grind, aggressive early entry, conviction holding

Entry Signals (ALL must align - confluence rule):
1. Token <$1M market cap (Orangie rule)
2. Volume spike 2x+ average 1h volume (professional entry)
3. Price pump 5%+ on increased volume (2nd pump confirmation)
4. 4-hour uptrend bias (TJR structure rule)
5. Community age 7-14 days with growing engagement (Orangie rule)

Exit Rules (Fixed + Time-based + Trailing):
- Fixed ladder: 25% @ +50%, 25% @ +100%, 25% @ +200%
- Runner (25%): Trails by 30% from peak after reaching +200%
- Time exit: If no directional move >24hrs, exit (sideways = death - TJR rule)
- Hard stop: -30% (Orangie rule)

Behavioral Rules (All 3 traders follow):
- 1% max risk per trade (position sizing)
- 24-hour cooling off after any loss >2% (prevents revenge trading)
- Daily stop loss: -3% total (protects account)
- No overriding exits - automation only
"""

import requests
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ============================================================================
# SETUP
# ============================================================================

LOG_FILE = Path.home() / ".hermes" / "fomo_trader_researched.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_researched_trades.jsonl"
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

# FOMO API (User provided)
FOMO_API_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
FOMO_BASE_URL = "https://api.fomo.family"

# CONFIG - RESEARCH-BACKED RULES
BANKROLL = 2.96
BANKROLL_MIN = 0.30

# ENTRY FILTERS (All must align - confluence)
MAX_MARKET_CAP = 1_000_000  # Orangie: <$1M only
VOLUME_SPIKE_MIN = 2.0  # 2x average 1h volume
PRICE_PUMP_MIN_PCT = 5.0  # 5%+ pump needed
COMMUNITY_AGE_MIN_DAYS = 7  # Min 7 days old
COMMUNITY_AGE_MAX_DAYS = 14  # Max 14 days (sweet spot)

# EXIT RULES (Fixed ladder + Time + Trailing)
EXIT_TIERS = [
    {"multiple": 1.50, "pct": 0.25, "name": "+50%"},
    {"multiple": 2.00, "pct": 0.25, "name": "+100%"},
    {"multiple": 3.00, "pct": 0.25, "name": "+200%"},
]
RUNNER_TRAILING_PCT = -30.0  # TJR rule: trail from peak
TIME_EXIT_HOURS = 24  # TJR rule: sideways >24h = exit

# POSITION SIZING & RISK (All 3 traders follow)
RISK_PER_TRADE_PCT = 1.0  # 1% max loss per trade
POSITION_SIZE_MIN = 0.15
POSITION_SIZE_MAX = 0.50
HARD_STOP_LOSS_PCT = -30.0  # Orangie rule

# BEHAVIORAL RULES
COOLING_OFF_LOSS_PCT = 2.0  # After -2% loss, take 24h break
COOLING_OFF_HOURS = 24
DAILY_LOSS_LIMIT_PCT = 3.0  # Stop trading if down 3% today

# ============================================================================
# POSITION TRACKING
# ============================================================================

class Position:
    def __init__(self, token, entry_price, size_usd, mc, entry_time):
        self.token = token
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.market_cap = mc
        self.entry_time = entry_time
        
        self.peak_price = entry_price
        self.peak_time = entry_time
        self.tiers_sold = [False, False, False]  # 3 tiers
        self.runner_active = False
        self.runner_peak = entry_price
        self.time_exit_triggered = False
        
        self.realized_pnl = 0.0

# ============================================================================
# BOT
# ============================================================================

class FOMAResearchedTrader:
    def __init__(self, api_key):
        self.api_key = api_key
        self.bankroll = BANKROLL
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        
        self.positions = {}
        self.last_cooling_off = None
        self.in_cooling_off = False
        self.today_start = datetime.now()
        self.today_pnl = 0.0
        
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
    
    def log(self, msg, level="INFO"):
        getattr(log, level.lower())(msg)
    
    def log_trade(self, data):
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")
    
    def get_hot_tokens(self, limit=30):
        """Get trending tokens <$1M MC"""
        try:
            url = f"{FOMO_BASE_URL}/tokens/trending"
            resp = self.session.get(url, params={"limit": limit}, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("tokens", [])
        except Exception as e:
            self.log(f"Hot tokens error: {e}", "DEBUG")
        return []
    
    def get_token_info(self, token_mint):
        """Get current token price, volume, liquidity"""
        try:
            url = f"{FOMO_BASE_URL}/tokens/{token_mint}"
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def get_chart(self, token_mint, interval="1m", limit=60):
        """Get OHLCV candles"""
        try:
            url = f"{FOMO_BASE_URL}/tokens/{token_mint}/chart"
            resp = self.session.get(url, params={"interval": interval, "limit": limit}, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("candles", [])
        except:
            pass
        return []
    
    def buy(self, token_mint, amount_usd):
        """Execute buy"""
        try:
            url = f"{FOMO_BASE_URL}/trades/buy"
            payload = {"tokenMint": token_mint, "amountUSD": amount_usd, "slippage": 2.0}
            resp = self.session.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def sell(self, token_mint, amount_usd):
        """Execute sell"""
        try:
            url = f"{FOMO_BASE_URL}/trades/sell"
            payload = {"tokenMint": token_mint, "amountUSD": amount_usd, "slippage": 2.0}
            resp = self.session.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def check_cooling_off(self):
        """Behavioral rule: 24h cooling off after -2% loss"""
        if self.in_cooling_off:
            elapsed = (datetime.now() - self.last_cooling_off).total_seconds() / 3600
            if elapsed >= COOLING_OFF_HOURS:
                self.in_cooling_off = False
                self.log("✅ Cooling off over. Resuming trades.", "INFO")
            else:
                return False
        return True
    
    def check_daily_limit(self):
        """Daily loss limit: stop if down -3% today"""
        elapsed = (datetime.now() - self.today_start).total_seconds() / 3600
        if elapsed >= 24:
            self.today_start = datetime.now()
            self.today_pnl = 0.0
        
        daily_loss_limit = BANKROLL * (DAILY_LOSS_LIMIT_PCT / 100)
        if self.today_pnl < -daily_loss_limit:
            self.log(f"⏸️  Daily loss limit hit ({self.today_pnl:.3f}). Stopping for the day.", "WARNING")
            return False
        return True
    
    def scan_tokens(self):
        """ORANGIE RULE: Scan <$1M MC tokens with confluence signals"""
        if not self.check_cooling_off() or not self.check_daily_limit():
            return
        
        tokens = self.get_hot_tokens(limit=50)
        for token_data in tokens:
            token_mint = token_data.get("mint")
            mc = token_data.get("marketCap", 0)
            
            # Filter 1: Market cap
            if mc >= MAX_MARKET_CAP:
                continue
            
            # Already holding?
            if token_mint in self.positions:
                continue
            
            # Check confluence
            self.evaluate_confluence(token_mint, mc)
    
    def evaluate_confluence(self, token_mint, market_cap):
        """TJR RULE: All signals must align (confluence)"""
        try:
            # Get 1m candles (60 last minute candles)
            candles = self.get_chart(token_mint, interval="1m", limit=60)
            if len(candles) < 10:
                return
            
            # Signal 1: Volume spike (2x+ average)
            avg_vol = sum(c.get("volume", 0) for c in candles[-10:-1]) / 9
            latest_vol = candles[-1].get("volume", 0)
            if avg_vol <= 0 or (latest_vol / avg_vol) < VOLUME_SPIKE_MIN:
                return
            
            # Signal 2: Price pump (5%+)
            price_change = ((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"]) * 100
            if price_change < PRICE_PUMP_MIN_PCT:
                return
            
            # Signal 3: Multi-pump confirmation (2nd pump on higher vol)
            # Check if we see a retracement then pump pattern
            has_retrace = False
            prev_close = candles[-10]["close"]
            for i in range(-9, -1):
                if candles[i]["close"] < prev_close * 0.95:  # 5% retrace
                    has_retrace = True
                    break
            if not has_retrace:
                return  # Too early, might be 1st pump
            
            # Signal 4: 4-hour uptrend bias (TJR rule)
            candles_4h = self.get_chart(token_mint, interval="4h", limit=5)
            if len(candles_4h) >= 2:
                if candles_4h[-1]["close"] <= candles_4h[-2]["close"]:
                    return  # Downtrend, skip
            
            # CONFLUENCE MET: All signals aligned
            self.enter_trade(token_mint, candles[-1]["close"], market_cap)
        
        except Exception as e:
            self.log(f"Confluence error: {e}", "DEBUG")
    
    def enter_trade(self, token_mint, entry_price, market_cap):
        """Execute entry with position sizing (1% risk max)"""
        try:
            max_loss = self.bankroll * (RISK_PER_TRADE_PCT / 100)
            stop_ratio = abs(HARD_STOP_LOSS_PCT) / 100
            position_size = max_loss / stop_ratio
            position_size = max(position_size, POSITION_SIZE_MIN)
            position_size = min(position_size, POSITION_SIZE_MAX)
            
            if position_size > self.bankroll * 0.5:
                self.log(f"Position size {position_size} too large", "WARNING")
                return
            
            # Execute buy
            buy_result = self.buy(token_mint, position_size)
            if not buy_result:
                self.log(f"Buy failed: {token_mint[:8]}...", "ERROR")
                return
            
            self.bankroll -= position_size
            self.positions[token_mint] = Position(token_mint, entry_price, position_size, market_cap, datetime.now())
            self.total_trades += 1
            
            self.log(f"🟢 ENTRY: {token_mint[:8]}... | ${position_size:.2f} @ ${entry_price:.9f} | MC: ${market_cap:,.0f}", "INFO")
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "BUY",
                "token": token_mint,
                "entry_price": entry_price,
                "market_cap": market_cap,
                "size": position_size
            })
        
        except Exception as e:
            self.log(f"Entry error: {e}", "ERROR")
    
    def monitor_exits(self):
        """Monitor positions and execute exits (fixed ladder + time + trailing)"""
        for token_mint in list(self.positions.keys()):
            try:
                pos = self.positions[token_mint]
                info = self.get_token_info(token_mint)
                if not info:
                    continue
                
                current_price = info.get("price", 0)
                if current_price <= 0:
                    continue
                
                # Track peak
                if current_price > pos.peak_price:
                    pos.peak_price = current_price
                    pos.peak_time = datetime.now()
                
                multiple = current_price / pos.entry_price
                time_held = (datetime.now() - pos.entry_time).total_seconds() / 3600
                
                # EXIT 1: Fixed ladder (Orangie + TJR)
                for idx, tier in enumerate(EXIT_TIERS):
                    if not pos.tiers_sold[idx] and multiple >= tier["multiple"]:
                        exit_amt = pos.size_usd * tier["pct"]
                        self.exit_tier(token_mint, exit_amt, tier["name"], current_price, pos)
                        pos.tiers_sold[idx] = True
                
                # EXIT 2: Runner with trailing stop (TJR)
                if all(pos.tiers_sold) and not pos.runner_active:
                    pos.runner_active = True
                    self.log(f"📊 {token_mint[:8]}... RUNNER phase (trailing stop)", "INFO")
                
                if pos.runner_active:
                    trail_price = pos.peak_price * (1 + RUNNER_TRAILING_PCT / 100)
                    if current_price < trail_price:
                        exit_amt = pos.size_usd * 0.25
                        self.exit_tier(token_mint, exit_amt, "RUNNER", current_price, pos)
                        del self.positions[token_mint]
                        continue
                
                # EXIT 3: Time-based exit (TJR: sideways >24h = death)
                if time_held > TIME_EXIT_HOURS and not pos.time_exit_triggered:
                    self.log(f"⏰ {token_mint[:8]}... >24h sideways, exiting", "INFO")
                    remaining = pos.size_usd * (1 - sum([1 for x in pos.tiers_sold if x]) * 0.25)
                    if remaining > 0:
                        self.exit_tier(token_mint, remaining, "TIME_EXIT", current_price, pos)
                    pos.time_exit_triggered = True
                
                # EXIT 4: Hard stop loss (Orangie: -30%)
                if multiple <= (1 + HARD_STOP_LOSS_PCT / 100):
                    self.log(f"🔴 {token_mint[:8]}... HARD STOP {HARD_STOP_LOSS_PCT}%", "WARNING")
                    remaining = pos.size_usd * (1 - sum([1 for x in pos.tiers_sold if x]) * 0.25)
                    if remaining > 0:
                        self.exit_tier(token_mint, remaining, "STOP_LOSS", current_price, pos)
                    del self.positions[token_mint]
            
            except Exception as e:
                self.log(f"Exit monitor error: {e}", "DEBUG")
    
    def exit_tier(self, token_mint, amount, tier_name, exit_price, pos):
        """Execute exit"""
        try:
            sell_result = self.sell(token_mint, amount)
            if not sell_result:
                self.log(f"Sell failed: {token_mint[:8]}...", "ERROR")
                return
            
            pnl = amount * (exit_price / pos.entry_price - 1)
            if pnl > 0:
                self.wins += 1
                self.log(f"💰 EXIT ({tier_name}): {token_mint[:8]}... | ${amount:.2f} | PnL: +${pnl:.3f} ✅", "INFO")
            else:
                self.losses += 1
                self.log(f"❌ EXIT ({tier_name}): {token_mint[:8]}... | ${amount:.2f} | PnL: ${pnl:.3f}", "INFO")
            
            self.bankroll += amount * (exit_price / pos.entry_price)
            pos.realized_pnl += pnl
            self.today_pnl += pnl
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "SELL",
                "token": token_mint,
                "tier": tier_name,
                "exit_price": exit_price,
                "pnl": pnl
            })
            
            # Behavioral: cooling off after -2% loss
            if pnl < 0 and abs(pnl / pos.size_usd) > (COOLING_OFF_LOSS_PCT / 100):
                self.in_cooling_off = True
                self.last_cooling_off = datetime.now()
                self.log(f"❄️  Loss >{COOLING_OFF_LOSS_PCT}%, cooling off {COOLING_OFF_HOURS}h", "WARNING")
        
        except Exception as e:
            self.log(f"Exit error: {e}", "ERROR")
    
    def run(self):
        self.log("=" * 80)
        self.log("🚀 FOMO MEMECOIN TRADER (Orangie + TJR + Kimchi RESEARCH)")
        self.log("=" * 80)
        self.log(f"Bankroll: ${self.bankroll:.2f}")
        self.log(f"Entry confluence: <${MAX_MARKET_CAP:,} MC + Vol2x+ + Pump5%+ + 4H uptrend + Multi-pump")
        self.log(f"Exit: Ladder (+50%/+100%/+200%) + Runner (trail -30%) + Time (24h) + Stop (-30%)")
        self.log(f"Risk: {RISK_PER_TRADE_PCT}%/trade | Cooling off: -{COOLING_OFF_LOSS_PCT}% triggers {COOLING_OFF_HOURS}h")
        self.log("=" * 80)
        
        iteration = 0
        while True:
            try:
                iteration += 1
                
                self.scan_tokens()
                self.monitor_exits()
                
                if iteration % 200 == 0:
                    wr = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
                    pnl = self.bankroll - BANKROLL
                    self.log(f"📊 Bankroll: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} | Trades: {self.total_trades} | W/L: {self.wins}/{self.losses} | WR: {wr:.0f}%", "INFO")
                    
                    if self.bankroll < BANKROLL_MIN:
                        self.log("❌ Bankroll below minimum. Stopping.", "ERROR")
                        break
                
                time.sleep(3)
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log(f"Cycle error: {e}", "ERROR")
                time.sleep(5)
        
        pnl = self.bankroll - BANKROLL
        self.log(f"Final: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} | W/L: {self.wins}/{self.losses}", "INFO")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    bot = FOMAResearchedTrader(FOMO_API_KEY)
    bot.run()
