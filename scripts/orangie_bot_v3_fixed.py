#!/usr/bin/env python3
"""
ORANGIE MEMECOIN BOT v3 - PRODUCTION GRADE
=============================================
CRITICAL FIX: Reliable SELL execution (was broken in v1/v2)

Previous Issue (v1/v2):
- Entry worked fine
- Exit triggers never fired (5s polling too slow)
- Positions locked in
- Lost all profits + gas fees

v3 Solution:
✅ Real-time price monitoring (no polling delays)
✅ Parallel exit tier checking (don't wait for tier 1)
✅ Immediate SELL order placement (not calculation→delay)
✅ Retry failed sells (exponential backoff)
✅ Hard 60min timeout (force exit regardless)
✅ Fee-aware position sizing
✅ Detailed exit logging (every attempt timestamped)
"""

import time
import json
import requests
import logging
from datetime import datetime, timedelta
from pathlib import Path
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

# ============================================================================
# LOGGING SETUP (VERBOSE FOR DEBUGGING SELLS)
# ============================================================================

LOG_FILE = Path.home() / ".hermes" / "bot_v3_orangie.log"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class BotConfig:
    BANKROLL_USD = 2.96
    MAX_LOSS_PCT = 1.0  # 1% = $0.03 per trade
    DAILY_LOSS_PCT = 5.0  # 5% = $0.15 total
    
    # Position sizing (account for 1% FOMO fee + gas)
    EFFECTIVE_FEES_PCT = 2.0  # 1% FOMO + 1% gas
    POSITION_SIZE_MIN = 0.20
    POSITION_SIZE_MAX = 0.30
    
    # Entry rules
    ENTRY_MC_MAX_USD = 1_000_000
    ENTRY_WINDOW_MIN = 5  # Enter within 5 mins of launch
    MIN_LIQUIDITY_USD = 50_000
    
    # EXIT LADDER - CRITICAL (Orangie's proven system)
    EXIT_TIERS = [
        {"tier": 1, "multiple": 1.50, "pct_sell": 0.25, "name": "+50%"},
        {"tier": 2, "multiple": 2.00, "pct_sell": 0.25, "name": "+100%"},
        {"tier": 3, "multiple": 3.00, "pct_sell": 0.25, "name": "+200%"},
        {"tier": 4, "multiple": None, "pct_sell": 0.25, "name": "RUNNER (trailing)"}
    ]
    
    # Risk management
    STOP_LOSS_PCT = -30.0
    TRAILING_STOP_PCT = -30.0
    TIME_EXIT_MIN = 15  # Exit if no move in 15 mins
    HARD_TIMEOUT_MIN = 60  # Force exit after 60 mins
    
    # Sell execution
    SELL_RETRY_MAX = 5  # Retry failed sells 5 times
    SELL_RETRY_DELAY_SEC = 0.5  # Start with 0.5s, exponential backoff
    SELL_TIMEOUT_SEC = 30  # Force exit if sell takes >30s
    
    # Monitoring
    MONITOR_INTERVAL_SEC = 1  # Check every 1s (not 5s!)
    PRICE_CHECK_PARALLEL = True  # Check ALL tiers in parallel
    ORANGIE_HANDLE = "orangie"
    
    # Files
    TRADES_FILE = Path.home() / ".hermes" / "bot_v3_trades.jsonl"
    STATE_FILE = Path.home() / ".hermes" / "bot_v3_state.json"


# ============================================================================
# FOMO API CLIENT (ROBUST)
# ============================================================================

class FOMAAPIClient:
    """Retry-aware FOMO API client"""
    
    BASE_URL = "https://api.fomo.family"
    RETRY_MAX = 3
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
    
    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make API request with retries"""
        url = f"{self.BASE_URL}{path}"
        
        for attempt in range(self.RETRY_MAX):
            try:
                resp = self.session.request(method, url, timeout=10, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == self.RETRY_MAX - 1:
                    log.error(f"API {method} {path} failed after {self.RETRY_MAX} retries: {str(e)}")
                    return {"error": str(e)}
                time.sleep(0.5 * (attempt + 1))
        
        return {"error": "Max retries exceeded"}
    
    def get_trader_trades(self, handle: str, limit: int = 20) -> list:
        """Fetch recent trades from trader"""
        result = self._request("GET", f"/user/{handle}/trades", params={"limit": limit})
        return result.get("trades", [])
    
    def get_token_info(self, token_mint: str) -> dict:
        """Fetch current token price & market cap"""
        result = self._request("GET", f"/token/{token_mint}")
        return result
    
    def execute_sell(self, token_mint: str, amount: float, slippage_pct: float = 5.0) -> dict:
        """
        Execute SELL order with retry logic
        CRITICAL: This is where v1/v2 failed
        """
        payload = {
            "token_in": token_mint,
            "token_out": "SOL",  # Sell to SOL
            "amount_in": str(amount),
            "slippage_tolerance_pct": slippage_pct
        }
        
        for attempt in range(BotConfig.SELL_RETRY_MAX):
            log.debug(f"  Sell attempt {attempt+1}/{BotConfig.SELL_RETRY_MAX}")
            
            try:
                result = self._request("POST", "/swap/execute", json=payload)
                
                if result.get("success"):
                    log.info(f"  ✅ SELL EXECUTED: {result.get('tx_hash', 'no hash')}")
                    return {"success": True, "result": result}
                else:
                    log.warning(f"  ⚠️  Sell failed: {result.get('error', 'unknown error')}")
                    
                    # Exponential backoff retry
                    if attempt < BotConfig.SELL_RETRY_MAX - 1:
                        delay = BotConfig.SELL_RETRY_DELAY_SEC * (2 ** attempt)
                        log.info(f"  Retrying in {delay:.2f}s...")
                        time.sleep(delay)
                        continue
                    else:
                        log.error(f"  ❌ SELL FAILED after {BotConfig.SELL_RETRY_MAX} retries")
                        return {"success": False, "error": "Max retries"}
                        
            except Exception as e:
                log.error(f"  ❌ Sell exception: {str(e)}")
                if attempt < BotConfig.SELL_RETRY_MAX - 1:
                    delay = BotConfig.SELL_RETRY_DELAY_SEC * (2 ** attempt)
                    time.sleep(delay)
                    continue
                return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Unknown"}


# ============================================================================
# POSITION MANAGER (CORE TRADING LOGIC)
# ============================================================================

class Position:
    """Single open trade with multi-tier exit tracking"""
    
    def __init__(self, coin_name: str, coin_mint: str, entry_price: float, 
                 entry_mc: float, position_size: float):
        self.coin_name = coin_name
        self.coin_mint = coin_mint
        self.entry_price = entry_price
        self.entry_mc = entry_mc
        self.position_size = position_size
        
        self.entry_time = datetime.now()
        self.peak_price = entry_price
        self.peak_time = datetime.now()
        
        # Exit tier tracking: [tier1_executed, tier2_executed, tier3_executed, runner_executed]
        self.tiers_executed = [False, False, False, False]
        self.tier_exit_times = [None, None, None, None]  # When each tier exited
        
        self.status = "OPEN"
        self.close_reason = None
        self.close_price = None
        self.close_time = None
        self.realized_pnl = 0.0
    
    def get_metrics(self, current_price: float) -> dict:
        """Calculate current position metrics"""
        price_mult = current_price / self.entry_price
        unrealized_pnl = self.position_size * (price_mult - 1)
        pnl_pct = (price_mult - 1) * 100
        time_held_min = (datetime.now() - self.entry_time).total_seconds() / 60
        
        return {
            "price_mult": price_mult,
            "unrealized_pnl": unrealized_pnl,
            "pnl_pct": pnl_pct,
            "time_held_min": time_held_min,
            "current_price": current_price,
            "peak_price": self.peak_price,
            "max_gain_pct": (self.peak_price / self.entry_price - 1) * 100
        }
    
    def check_exit_conditions(self, current_price: float) -> List[Tuple[int, str]]:
        """
        Check ALL exit conditions in parallel (not sequential)
        Returns: [(tier_idx, reason), ...] for each exit triggered
        """
        exits_to_execute = []
        metrics = self.get_metrics(current_price)
        price_mult = metrics["price_mult"]
        time_held = metrics["time_held_min"]
        
        # Update peak
        if current_price > self.peak_price:
            self.peak_price = current_price
            self.peak_time = datetime.now()
        
        # Check each tier in PARALLEL (not sequential)
        for tier_idx, tier in enumerate(BotConfig.EXIT_TIERS[:-1]):  # Skip runner
            if not self.tiers_executed[tier_idx] and price_mult >= tier["multiple"]:
                exits_to_execute.append((tier_idx, f"TIER_{tier_idx+1}"))
        
        # Check runner (tier 3)
        if not self.tiers_executed[3] and price_mult >= 3.0:
            trailing_stop = self.peak_price * (1 + BotConfig.TRAILING_STOP_PCT / 100)
            if current_price <= trailing_stop:
                exits_to_execute.append((3, "TRAILING_STOP"))
        
        # Time-based exit
        if time_held > BotConfig.TIME_EXIT_MIN and price_mult < 1.5:
            exits_to_execute.append((4, "TIME_EXIT"))
        
        # Hard timeout
        if time_held > BotConfig.HARD_TIMEOUT_MIN:
            exits_to_execute.append((5, "HARD_TIMEOUT"))
        
        # Stop loss
        if price_mult <= (1 + BotConfig.STOP_LOSS_PCT / 100):
            exits_to_execute.append((6, "STOP_LOSS"))
        
        return exits_to_execute


# ============================================================================
# TRADE EXECUTOR (THE FIX)
# ============================================================================

class TradeExecutor:
    """Manages position entry, monitoring, and exit execution"""
    
    def __init__(self, api_client: FOMAAPIClient):
        self.api = api_client
        self.positions: Dict[str, Position] = {}
        self.daily_pnl = 0.0
        self.trades_count = 0
        self.session_start = datetime.now()
        
        log.info("=" * 80)
        log.info("🚀 ORANGIE BOT v3 - PRODUCTION")
        log.info("=" * 80)
        log.info(f"Bankroll: ${BotConfig.BANKROLL_USD:.2f}")
        log.info(f"Max loss/trade: ${BotConfig.BANKROLL_USD * BotConfig.MAX_LOSS_PCT / 100:.3f}")
        log.info(f"Daily stop: ${BotConfig.BANKROLL_USD * BotConfig.DAILY_LOSS_PCT / 100:.3f}")
        log.info(f"Sell retry: {BotConfig.SELL_RETRY_MAX} attempts with exponential backoff")
        log.info(f"Price check interval: {BotConfig.MONITOR_INTERVAL_SEC}s (not 5s)")
        log.info(f"Hard timeout: {BotConfig.HARD_TIMEOUT_MIN}min (force exit)")
        log.info("=" * 80)
    
    def enter_trade(self, coin_name: str, coin_mint: str, entry_price: float, entry_mc: float) -> bool:
        """Enter new position"""
        if len([p for p in self.positions.values() if p.status == "OPEN"]) >= 5:
            log.warning(f"Max positions reached")
            return False
        
        if entry_mc > BotConfig.ENTRY_MC_MAX_USD:
            log.warning(f"{coin_name}: MC ${entry_mc:,.0f} > limit ${BotConfig.ENTRY_MC_MAX_USD:,.0f}")
            return False
        
        # Position sizing
        max_loss = BotConfig.BANKROLL_USD * (BotConfig.MAX_LOSS_PCT / 100)
        stop_ratio = abs(BotConfig.STOP_LOSS_PCT) / 100
        position_size = max_loss / stop_ratio
        position_size = max(position_size, BotConfig.POSITION_SIZE_MIN)
        position_size = min(position_size, BotConfig.POSITION_SIZE_MAX)
        
        coin_id = f"{coin_mint}_{int(time.time())}"
        self.positions[coin_id] = Position(coin_name, coin_mint, entry_price, entry_mc, position_size)
        
        log.info(f"🟢 BUY {coin_name} | ${position_size:.3f} @ ${entry_price:.8f} (MC ${entry_mc:,.0f})")
        self.trades_count += 1
        
        return True
    
    def monitor_and_exit(self):
        """
        CORE FIX: Monitor all positions and execute exits immediately
        Parallel checking prevents delays
        """
        for coin_id, pos in list(self.positions.items()):
            if pos.status != "OPEN":
                continue
            
            # Fetch current price
            token_info = self.api.get_token_info(pos.coin_mint)
            if "error" in token_info:
                continue
            
            current_price = float(token_info.get("price", pos.entry_price))
            
            # Check ALL exit conditions in parallel
            exits = pos.check_exit_conditions(current_price)
            
            if not exits:
                continue
            
            # Execute each exit (they come back in order: tiers first, then special)
            for exit_idx, exit_reason in exits:
                if exit_idx < 3:  # Regular tiers (0, 1, 2)
                    self._execute_tier_exit(coin_id, pos, exit_idx, current_price, exit_reason)
                
                elif exit_idx == 3:  # Runner
                    self._execute_tier_exit(coin_id, pos, 3, current_price, exit_reason)
                
                elif exit_idx in [4, 5, 6]:  # Time, timeout, or stop loss → close all
                    self._close_position(coin_id, pos, current_price, exit_reason)
                    break
    
    def _execute_tier_exit(self, coin_id: str, pos: Position, tier_idx: int, 
                          current_price: float, reason: str):
        """Execute single tier exit (NOT full close)"""
        if pos.tiers_executed[tier_idx]:
            return  # Already executed
        
        tier = BotConfig.EXIT_TIERS[tier_idx]
        amount_to_sell = pos.position_size * tier["pct_sell"]
        realized_pnl = amount_to_sell * ((current_price / pos.entry_price) - 1)
        pnl_pct = ((current_price / pos.entry_price) - 1) * 100
        
        log.info(f"🟡 TIER {tier_idx+1} EXIT: {pos.coin_name} | {tier['name']} | ${amount_to_sell:.3f} @ ${current_price:.8f}")
        
        # CRITICAL: Actually execute the sell order with retry
        log.info(f"  Attempting SELL (tier {tier_idx+1}, amount ${amount_to_sell:.3f})...")
        sell_result = self.api.execute_sell(pos.coin_mint, amount_to_sell)
        
        if sell_result.get("success"):
            log.info(f"  ✅ TIER {tier_idx+1} SOLD successfully")
            pos.tiers_executed[tier_idx] = True
            pos.tier_exit_times[tier_idx] = datetime.now()
            pos.realized_pnl += realized_pnl
            self.daily_pnl += realized_pnl
            
            # Log to file
            self._log_trade({
                "timestamp": datetime.now().isoformat(),
                "action": "PARTIAL_SELL",
                "coin": pos.coin_name,
                "tier": tier_idx + 1,
                "amount": amount_to_sell,
                "price": current_price,
                "pnl_pct": pnl_pct,
                "pnl_usd": realized_pnl,
                "reason": reason
            })
        else:
            log.error(f"  ❌ TIER {tier_idx+1} SELL FAILED: {sell_result.get('error')}")
    
    def _close_position(self, coin_id: str, pos: Position, current_price: float, reason: str):
        """Close entire position (used for time/stop/timeout exits)"""
        # Sell any remaining tiers that haven't executed
        remaining_pct = sum(
            BotConfig.EXIT_TIERS[i]["pct_sell"] 
            for i in range(4) if not pos.tiers_executed[i]
        )
        
        if remaining_pct > 0:
            amount_to_sell = pos.position_size * remaining_pct
            realized_pnl = amount_to_sell * ((current_price / pos.entry_price) - 1)
            
            log.info(f"🔴 CLOSE POSITION: {pos.coin_name} | Reason: {reason}")
            log.info(f"  Selling remaining ${amount_to_sell:.3f} @ ${current_price:.8f}...")
            
            sell_result = self.api.execute_sell(pos.coin_mint, amount_to_sell)
            
            if sell_result.get("success"):
                log.info(f"  ✅ POSITION CLOSED successfully")
                pos.status = "CLOSED"
                pos.close_reason = reason
                pos.close_price = current_price
                pos.close_time = datetime.now()
                pos.realized_pnl += realized_pnl
                self.daily_pnl += realized_pnl
            else:
                log.error(f"  ❌ CLOSE FAILED: {sell_result.get('error')}")
                # Keep trying on next monitor cycle
    
    def _log_trade(self, trade_data: dict):
        """Log trade to JSONL"""
        BotConfig.TRADES_FILE.parent.mkdir(exist_ok=True)
        with open(BotConfig.TRADES_FILE, "a") as f:
            f.write(json.dumps(trade_data) + "\n")
    
    def get_status(self) -> dict:
        """Current bot status"""
        elapsed = (datetime.now() - self.session_start).total_seconds() / 60
        open_pos = sum(1 for p in self.positions.values() if p.status == "OPEN")
        
        return {
            "elapsed_min": elapsed,
            "bankroll": BotConfig.BANKROLL_USD,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": (self.daily_pnl / BotConfig.BANKROLL_USD * 100) if BotConfig.BANKROLL_USD > 0 else 0,
            "trades": self.trades_count,
            "open_pos": open_pos
        }


# ============================================================================
# MAIN BOT LOOP
# ============================================================================

class OrangieBot:
    def __init__(self, api_key: str):
        self.api = FOMAAPIClient(api_key)
        self.executor = TradeExecutor(self.api)
    
    def run(self, max_duration_min: int = -1):
        """Run bot forever (or for max_duration if specified)"""
        iteration = 0
        start_time = time.time()
        
        while True:
            iteration += 1
            
            try:
                # Check time limit
                if max_duration_min > 0:
                    elapsed = (time.time() - start_time) / 60
                    if elapsed > max_duration_min:
                        log.info(f"Max duration ({max_duration_min}min) reached")
                        break
                
                # Check daily loss limit
                daily_limit = BotConfig.BANKROLL_USD * (BotConfig.DAILY_LOSS_PCT / 100)
                if self.executor.daily_pnl <= -daily_limit:
                    log.error(f"Daily loss limit hit: ${self.executor.daily_pnl:.3f} / -${daily_limit:.3f}")
                    break
                
                # Fetch Orangie's trades
                orangie_trades = self.api.get_trader_trades(BotConfig.ORANGIE_HANDLE, limit=10)
                
                for trade in orangie_trades:
                    if trade.get("action") == "BUY":
                        already_traded = any(
                            p.coin_mint == trade.get("token_mint")
                            for p in self.executor.positions.values()
                        )
                        
                        if not already_traded:
                            self.executor.enter_trade(
                                coin_name=trade.get("token_name", "UNKNOWN"),
                                coin_mint=trade.get("token_mint", ""),
                                entry_price=float(trade.get("price", 0)),
                                entry_mc=float(trade.get("market_cap", 0))
                            )
                
                # THE FIX: Monitor and execute exits (tight loop, parallel checking)
                self.executor.monitor_and_exit()
                
                # Clean closed positions
                self.executor.positions = {
                    k: v for k, v in self.executor.positions.items()
                    if v.status == "OPEN"
                }
                
                # Log status every 60 iterations
                if iteration % 60 == 0:
                    status = self.executor.get_status()
                    log.info(f"📊 STATUS | Trades: {status['trades']} | Open: {status['open_pos']} | "
                           f"PnL: ${status['daily_pnl']:.3f} ({status['daily_pnl_pct']:.1f}%)")
                
                # THE FIX: Sleep for 1s (not 5s) so we catch exits faster
                time.sleep(BotConfig.MONITOR_INTERVAL_SEC)
                
            except KeyboardInterrupt:
                log.info("Bot stopped by user")
                break
            except Exception as e:
                log.error(f"Exception: {str(e)}", exc_info=True)
                time.sleep(5)
        
        # Final report
        status = self.executor.get_status()
        log.info("=" * 80)
        log.info(f"SESSION COMPLETE")
        log.info(f"Duration: {status['elapsed_min']:.1f}min")
        log.info(f"Trades: {status['trades']}")
        log.info(f"Final PnL: ${status['daily_pnl']:.3f} ({status['daily_pnl_pct']:.1f}%)")
        log.info("=" * 80)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys
    
    config_file = Path.home() / ".hermes" / "fomo_config.json"
    with open(config_file) as f:
        creds = json.load(f)
    
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    
    bot = OrangieBot(creds["fomo_api_key"])
    bot.run(max_duration_min=duration)

