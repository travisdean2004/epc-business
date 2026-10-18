#!/usr/bin/env python3
"""
FOMO MEMECOIN TRADER - TEST MODE (Paper Trading on Real Coins)
===============================================================
Oct 12, 2026

TEST MODE FEATURES:
- Real FOMO coin prices (not simulated)
- Paper trades (fake money, no actual spending)
- Looser entry filters (catch more trades to test strategy)
- Full logging for accuracy review
- 1-2 hour test before live deployment

LOOSENED ENTRY FILTERS (vs strict version):
- MC <$2M (vs $1M) - more opportunities
- Volume spike 1.5x+ (vs 2x) - catch earlier
- Price pump 3%+ (vs 5%) - more entries
- Skip 4H bias check - move faster
- Skip multi-pump check - catch 1st pump too

EXIT RULES (Same as live):
- Fixed ladder: 25% @ +50%, 25% @ +100%, 25% @ +200%
- Runner (25%): Trailing -30% from peak
- Time exit: 24h sideways = exit
- Hard stop: -30%
"""

import requests
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================================
# SETUP
# ============================================================================

LOG_FILE = Path.home() / ".hermes" / "fomo_testmode.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_testmode_trades.jsonl"
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

# FOMO API
FOMO_API_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
FOMO_BASE_URL = "https://api.fomo.family"

# CONFIG - LOOSENED FOR TESTING
BANKROLL = 2.96
BANKROLL_MIN = 0.30

# ENTRY FILTERS (LOOSENED)
MAX_MARKET_CAP = 2_000_000  # Looser: $2M (vs $1M)
VOLUME_SPIKE_MIN = 1.5  # Looser: 1.5x (vs 2x)
PRICE_PUMP_MIN_PCT = 3.0  # Looser: 3%+ (vs 5%+)

# EXIT RULES (Same)
EXIT_TIERS = [
    {"multiple": 1.50, "pct": 0.25, "name": "+50%"},
    {"multiple": 2.00, "pct": 0.25, "name": "+100%"},
    {"multiple": 3.00, "pct": 0.25, "name": "+200%"},
]
RUNNER_TRAILING_PCT = -30.0
TIME_EXIT_HOURS = 24

# POSITION SIZING & RISK
RISK_PER_TRADE_PCT = 1.0
POSITION_SIZE_MIN = 0.10
POSITION_SIZE_MAX = 0.50
HARD_STOP_LOSS_PCT = -30.0

# BEHAVIORAL
COOLING_OFF_LOSS_PCT = 2.0
COOLING_OFF_HOURS = 24
DAILY_LOSS_LIMIT_PCT = 3.0

# ============================================================================
# POSITION TRACKING
# ============================================================================

class TestPosition:
    def __init__(self, token, entry_price, size_usd, mc, entry_time):
        self.token = token
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.market_cap = mc
        self.entry_time = entry_time
        
        self.peak_price = entry_price
        self.peak_time = entry_time
        self.tiers_sold = [False, False, False]
        self.runner_active = False
        self.time_exit_triggered = False
        self.realized_pnl = 0.0
        self.last_price = entry_price

# ============================================================================
# TEST BOT
# ============================================================================

class FOMATestModeBot:
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
        self.test_start = datetime.now()
    
    def log(self, msg, level="INFO"):
        getattr(log, level.lower())(msg)
    
    def log_trade(self, data):
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")
    
    def get_hot_tokens(self, limit=50):
        """Get trending tokens from REAL FOMO API"""
        try:
            url = f"{FOMO_BASE_URL}/tokens/trending"
            resp = self.session.get(url, params={"limit": limit}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("tokens", [])
        except Exception as e:
            self.log(f"Hot tokens error: {e}", "DEBUG")
        return []
    
    def get_token_info(self, token_mint):
        """Get REAL token price, volume, liquidity"""
        try:
            url = f"{FOMO_BASE_URL}/tokens/{token_mint}"
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None
    
    def get_chart(self, token_mint, interval="1m", limit=60):
        """Get REAL candles from FOMO"""
        try:
            url = f"{FOMO_BASE_URL}/tokens/{token_mint}/chart"
            resp = self.session.get(url, params={"interval": interval, "limit": limit}, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("candles", [])
        except:
            pass
        return []
    
    def check_cooling_off(self):
        """Behavioral: 24h cooling off"""
        if self.in_cooling_off:
            elapsed = (datetime.now() - self.last_cooling_off).total_seconds() / 3600
            if elapsed >= COOLING_OFF_HOURS:
                self.in_cooling_off = False
                self.log("✅ Cooling off over.", "INFO")
            else:
                return False
        return True
    
    def check_daily_limit(self):
        """Daily loss limit"""
        elapsed = (datetime.now() - self.today_start).total_seconds() / 3600
        if elapsed >= 24:
            self.today_start = datetime.now()
            self.today_pnl = 0.0
        
        daily_limit = BANKROLL * (DAILY_LOSS_LIMIT_PCT / 100)
        if self.today_pnl < -daily_limit:
            self.log(f"⏸️  Daily limit hit. Stopping.", "WARNING")
            return False
        return True
    
    def scan_tokens(self):
        """Scan REAL FOMO tokens with LOOSENED filters"""
        if not self.check_cooling_off() or not self.check_daily_limit():
            return
        
        try:
            tokens = self.get_hot_tokens(limit=100)
            if not tokens:
                return
            
            for token_data in tokens:
                token_mint = token_data.get("mint")
                mc = token_data.get("marketCap", 0)
                
                # Filter 1: MC
                if mc >= MAX_MARKET_CAP:
                    continue
                
                # Already holding?
                if token_mint in self.positions:
                    continue
                
                # Evaluate entry
                self.evaluate_entry(token_mint, mc)
        
        except Exception as e:
            self.log(f"Scan error: {e}", "DEBUG")
    
    def evaluate_entry(self, token_mint, market_cap):
        """LOOSENED entry checks - catch more trades"""
        try:
            # Get real chart data
            candles = self.get_chart(token_mint, interval="1m", limit=30)
            if len(candles) < 5:
                return
            
            # Signal 1: Volume spike (1.5x+)
            avg_vol = sum(c.get("volume", 0) for c in candles[-10:-1]) / 9
            latest_vol = candles[-1].get("volume", 0)
            if avg_vol <= 0 or (latest_vol / avg_vol) < VOLUME_SPIKE_MIN:
                return
            
            # Signal 2: Price pump (3%+)
            price_change = ((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"]) * 100
            if price_change < PRICE_PUMP_MIN_PCT:
                return
            
            # ENTRY SIGNAL MET (loosened filters)
            self.enter_trade(token_mint, candles[-1]["close"], market_cap)
        
        except Exception as e:
            self.log(f"Entry eval error: {e}", "DEBUG")
    
    def enter_trade(self, token_mint, entry_price, market_cap):
        """PAPER TRADE: Simulate entry (no real money spent)"""
        try:
            max_loss = self.bankroll * (RISK_PER_TRADE_PCT / 100)
            stop_ratio = abs(HARD_STOP_LOSS_PCT) / 100
            position_size = max_loss / stop_ratio
            position_size = max(position_size, POSITION_SIZE_MIN)
            position_size = min(position_size, POSITION_SIZE_MAX)
            
            if position_size > self.bankroll * 0.5:
                return
            
            # PAPER TRADE (no actual money)
            self.bankroll -= position_size
            self.positions[token_mint] = TestPosition(token_mint, entry_price, position_size, market_cap, datetime.now())
            self.total_trades += 1
            
            self.log(f"📝 PAPER BUY: {token_mint[:8]}... | ${position_size:.2f} @ ${entry_price:.9f} | MC: ${market_cap:,.0f}", "INFO")
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "BUY",
                "token": token_mint,
                "entry_price": entry_price,
                "market_cap": market_cap,
                "size": position_size,
                "mode": "PAPER"
            })
        
        except Exception as e:
            self.log(f"Entry error: {e}", "ERROR")
    
    def monitor_exits(self):
        """Monitor PAPER positions against REAL price data"""
        for token_mint in list(self.positions.keys()):
            try:
                pos = self.positions[token_mint]
                info = self.get_token_info(token_mint)
                if not info:
                    continue
                
                current_price = info.get("price", 0)
                if current_price <= 0:
                    continue
                
                pos.last_price = current_price
                
                # Track peak
                if current_price > pos.peak_price:
                    pos.peak_price = current_price
                    pos.peak_time = datetime.now()
                
                multiple = current_price / pos.entry_price
                time_held = (datetime.now() - pos.entry_time).total_seconds() / 3600
                
                # EXIT 1: Fixed ladder
                for idx, tier in enumerate(EXIT_TIERS):
                    if not pos.tiers_sold[idx] and multiple >= tier["multiple"]:
                        exit_amt = pos.size_usd * tier["pct"]
                        self.exit_tier(token_mint, exit_amt, tier["name"], current_price, pos)
                        pos.tiers_sold[idx] = True
                
                # EXIT 2: Runner trailing stop
                if all(pos.tiers_sold) and not pos.runner_active:
                    pos.runner_active = True
                    self.log(f"📊 {token_mint[:8]}... RUNNER phase", "INFO")
                
                if pos.runner_active:
                    trail_price = pos.peak_price * (1 + RUNNER_TRAILING_PCT / 100)
                    if current_price < trail_price:
                        exit_amt = pos.size_usd * 0.25
                        self.exit_tier(token_mint, exit_amt, "RUNNER", current_price, pos)
                        del self.positions[token_mint]
                        continue
                
                # EXIT 3: Time-based
                if time_held > TIME_EXIT_HOURS and not pos.time_exit_triggered:
                    self.log(f"⏰ {token_mint[:8]}... >24h sideways", "INFO")
                    remaining = pos.size_usd * (1 - sum([1 for x in pos.tiers_sold if x]) * 0.25)
                    if remaining > 0:
                        self.exit_tier(token_mint, remaining, "TIME_EXIT", current_price, pos)
                    pos.time_exit_triggered = True
                
                # EXIT 4: Hard stop
                if multiple <= (1 + HARD_STOP_LOSS_PCT / 100):
                    self.log(f"🔴 {token_mint[:8]}... STOP {HARD_STOP_LOSS_PCT}%", "WARNING")
                    remaining = pos.size_usd * (1 - sum([1 for x in pos.tiers_sold if x]) * 0.25)
                    if remaining > 0:
                        self.exit_tier(token_mint, remaining, "STOP_LOSS", current_price, pos)
                    del self.positions[token_mint]
            
            except Exception as e:
                self.log(f"Exit monitor error: {e}", "DEBUG")
    
    def exit_tier(self, token_mint, amount, tier_name, exit_price, pos):
        """PAPER EXIT: Simulate exit"""
        try:
            pnl = amount * (exit_price / pos.entry_price - 1)
            
            if pnl > 0:
                self.wins += 1
                self.log(f"💰 PAPER SELL ({tier_name}): {token_mint[:8]}... | ${amount:.2f} | PnL: +${pnl:.3f} ✅", "INFO")
            else:
                self.losses += 1
                self.log(f"❌ PAPER SELL ({tier_name}): {token_mint[:8]}... | ${amount:.2f} | PnL: ${pnl:.3f}", "INFO")
            
            self.bankroll += amount * (exit_price / pos.entry_price)
            pos.realized_pnl += pnl
            self.today_pnl += pnl
            
            self.log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "SELL",
                "token": token_mint,
                "tier": tier_name,
                "exit_price": exit_price,
                "pnl": pnl,
                "mode": "PAPER"
            })
            
            # Behavioral: cooling off
            if pnl < 0 and abs(pnl / pos.size_usd) > (COOLING_OFF_LOSS_PCT / 100):
                self.in_cooling_off = True
                self.last_cooling_off = datetime.now()
                self.log(f"❄️  Loss >{COOLING_OFF_LOSS_PCT}%, cooling off {COOLING_OFF_HOURS}h", "WARNING")
        
        except Exception as e:
            self.log(f"Exit error: {e}", "ERROR")
    
    def run(self):
        self.log("=" * 80)
        self.log("🧪 FOMO MEMECOIN TRADER - TEST MODE (Paper Trading on Real Coins)")
        self.log("=" * 80)
        self.log(f"Starting bankroll: ${self.bankroll:.2f} (PAPER MONEY)")
        self.log(f"Entry filters (LOOSENED): <${MAX_MARKET_CAP:,} MC + Vol{VOLUME_SPIKE_MIN}x+ + Pump{PRICE_PUMP_MIN_PCT}%+")
        self.log(f"Exit: Ladder (+50%/+100%/+200%) + Runner (trail -30%) + Time (24h) + Stop (-30%)")
        self.log(f"Test duration: 1-2 hours, then review accuracy before going LIVE")
        self.log("=" * 80)
        
        iteration = 0
        while True:
            try:
                iteration += 1
                
                self.scan_tokens()
                self.monitor_exits()
                
                # Status every 100 iterations
                if iteration % 100 == 0:
                    elapsed = (datetime.now() - self.test_start).total_seconds() / 60
                    wr = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
                    pnl = self.bankroll - BANKROLL
                    
                    self.log(f"📊 [{elapsed:.0f}min] Bankroll: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} | Trades: {self.total_trades} | W/L: {self.wins}/{self.losses} | WR: {wr:.0f}% | Open: {len(self.positions)}", "INFO")
                    
                    # Auto-stop after 2 hours
                    if elapsed > 120:
                        self.log("⏹️  Test duration complete (2 hours). Review results and decide on LIVE deployment.", "INFO")
                        break
                    
                    if self.bankroll < BANKROLL_MIN:
                        self.log("❌ Bankroll below minimum. Stopping test.", "ERROR")
                        break
                
                time.sleep(3)
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log(f"Cycle error: {e}", "ERROR")
                time.sleep(5)
        
        # Final report
        elapsed = (datetime.now() - self.test_start).total_seconds() / 60
        pnl = self.bankroll - BANKROLL
        wr = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
        
        self.log("=" * 80)
        self.log(f"TEST COMPLETE ({elapsed:.0f} minutes)")
        self.log(f"Final bankroll: ${self.bankroll:.3f} | PnL: ${pnl:+.3f} ({(pnl/BANKROLL*100):+.1f}%)")
        self.log(f"Trades: {self.total_trades} | Wins: {self.wins} | Losses: {self.losses} | Win rate: {wr:.0f}%")
        self.log(f"Review: ~/.hermes/fomo_testmode_trades.jsonl")
        self.log("=" * 80)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    bot = FOMATestModeBot(FOMO_API_KEY)
    bot.run()
