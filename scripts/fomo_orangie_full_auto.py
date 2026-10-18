#!/usr/bin/env python3
"""
FOMO ORANGIE FULL AUTO-TRADER
Zero-touch trading: monitor Orangie's trades via API/network interception,
execute buys/sells autonomously, optimize exits, report only on major events.
"""

import json, os, sys, time, logging, asyncio, re, urllib.request, urllib.error, ssl
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.expanduser("~/.hermes/fomo_full_auto.log")),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("fomo_full_auto")

HOME = os.path.expanduser("~")
STATE_FILE = os.path.join(HOME, ".hermes/fomo_full_auto_state.json")
TRADES_FILE = os.path.join(HOME, ".hermes/fomo_full_auto_trades.jsonl")

# Load config
try:
    with open(os.path.join(HOME, ".hermes/fomo_config.json")) as f:
        CONFIG = json.load(f)
        FOMO_API_KEY = CONFIG.get("fomo_api_key")
        WALLET = CONFIG.get("wallet_public_key")
except:
    log.error("Missing FOMO config")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# API WRAPPER - Direct FOMO API calls
# ─────────────────────────────────────────────────────────────────────────────

class FOOMOTrader:
    def __init__(self):
        self.base_url = "https://api.fomo.family/v1"
        self.headers = {
            "Authorization": f"Bearer {FOMO_API_KEY}",
            "Content-Type": "application/json"
        }
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE
        
        self.positions = {}
        self.orangie_history = {}
        self.last_orangie_check = 0
        self.scan_interval = 5  # seconds
    
    def api_call(self, method, endpoint, data=None):
        """Make authenticated API call to FOMO."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == "GET":
                req = urllib.request.Request(url, headers=self.headers)
            else:
                payload = json.dumps(data).encode() if data else None
                req = urllib.request.Request(url, data=payload, headers=self.headers)
                req.get_method = lambda: method
            
            with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                return result
        except urllib.error.HTTPError as e:
            log.warning(f"API error {e.code}: {e.reason}")
            return None
        except Exception as e:
            log.error(f"API call failed: {e}")
            return None
    
    async def get_orangie_recent_trades(self):
        """Fetch Orangie's recent trades from FOMO."""
        try:
            # Attempt to fetch via user trades endpoint
            result = self.api_call("GET", "/user/orangie/trades?limit=20")
            
            if not result:
                log.debug("No trades fetched")
                return []
            
            trades = result.get("trades", [])
            new_trades = []
            
            for trade in trades:
                trade_id = trade.get("id")
                if trade_id not in self.orangie_history:
                    self.orangie_history[trade_id] = trade
                    new_trades.append(trade)
            
            return new_trades
        
        except Exception as e:
            log.error(f"Failed to fetch Orangie trades: {e}")
            return []
    
    async def execute_buy(self, coin_mint, amount_usd=2.0):
        """Execute buy order on FOMO."""
        try:
            log.info(f"🟢 BUYING {coin_mint} for ${amount_usd}")
            
            payload = {
                "token": coin_mint,
                "amount_usd": amount_usd,
                "slippage": 2.0,
            }
            
            result = self.api_call("POST", "/trades/buy", payload)
            
            if result and result.get("success"):
                tx_id = result.get("tx_id")
                entry_price = result.get("entry_price", 0)
                
                self.positions[coin_mint] = {
                    "entry_time": time.time(),
                    "entry_price": entry_price,
                    "amount_usd": amount_usd,
                    "tx_id": tx_id,
                    "status": "open",
                    "pnl_pct": 0,
                }
                
                log.info(f"✅ BUY EXECUTED: {coin_mint} | TX: {tx_id}")
                return True
            else:
                log.error(f"Buy failed: {result}")
                return False
        
        except Exception as e:
            log.error(f"Execute buy error: {e}")
            return False
    
    async def execute_sell(self, coin_mint):
        """Execute sell order."""
        try:
            if coin_mint not in self.positions:
                log.warning(f"No position for {coin_mint}")
                return False
            
            pos = self.positions[coin_mint]
            log.info(f"🟡 SELLING {coin_mint}")
            
            payload = {
                "token": coin_mint,
                "percent": 100,  # Sell all
                "slippage": 2.0,
            }
            
            result = self.api_call("POST", "/trades/sell", payload)
            
            if result and result.get("success"):
                exit_price = result.get("exit_price", 0)
                pnl_pct = ((exit_price - pos["entry_price"]) / pos["entry_price"] * 100) if pos["entry_price"] > 0 else 0
                pos["pnl_pct"] = pnl_pct
                pos["exit_time"] = time.time()
                pos["status"] = "closed"
                
                # Log trade
                trade_log = {
                    "ts": datetime.now().isoformat(),
                    "coin": coin_mint,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "hold_seconds": pos["exit_time"] - pos["entry_time"],
                    "amount_usd": pos["amount_usd"],
                }
                
                with open(TRADES_FILE, "a") as f:
                    f.write(json.dumps(trade_log) + "\n")
                
                log.info(f"✅ SELL EXECUTED: {coin_mint} | PnL: {pnl_pct:+.2f}%")
                del self.positions[coin_mint]
                return True
            else:
                log.error(f"Sell failed: {result}")
                return False
        
        except Exception as e:
            log.error(f"Execute sell error: {e}")
            return False
    
    async def check_position_pnl(self, coin_mint):
        """Get real-time PnL for an open position."""
        try:
            result = self.api_call("GET", f"/tokens/{coin_mint}/price")
            
            if result:
                current_price = result.get("price", 0)
                if coin_mint in self.positions:
                    pos = self.positions[coin_mint]
                    pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"] * 100) if pos["entry_price"] > 0 else 0
                    pos["pnl_pct"] = pnl_pct
                    return pnl_pct
            
            return 0
        except:
            return 0
    
    async def monitor_loop(self):
        """Main autonomous trading loop."""
        log.info("=" * 80)
        log.info("🤖 FOMO ORANGIE FULL AUTO-TRADER")
        log.info("   Status: LIVE AUTONOMOUS TRADING")
        log.info("   Monitor: Orangie (@orangie) trades")
        log.info("   Execute: Auto-buy on detection, auto-sell on exit signal")
        log.info("   Bankroll: $2.96 USD FOMO")
        log.info("   Scan interval: 5 seconds")
        log.info("=" * 80)
        
        scan_num = 0
        last_state_save = time.time()
        
        while True:
            try:
                scan_num += 1
                now = time.time()
                
                # Scan Orangie's recent trades
                if now - self.last_orangie_check > self.scan_interval:
                    log.debug(f"📡 Scan #{scan_num}: Checking Orangie's trades...")
                    
                    new_trades = await self.get_orangie_recent_trades()
                    
                    for trade in new_trades:
                        coin_mint = trade.get("token")
                        action = trade.get("action", "").upper()  # BUY or SELL
                        
                        log.info(f"🎯 ORANGIE {action}: {coin_mint}")
                        
                        if action == "BUY":
                            # Copy the buy
                            await self.execute_buy(coin_mint, amount_usd=2.0)
                        
                        elif action == "SELL":
                            # Exit our position
                            if coin_mint in self.positions:
                                await self.execute_sell(coin_mint)
                    
                    self.last_orangie_check = now
                
                # Monitor open positions
                for coin in list(self.positions.keys()):
                    pos = self.positions[coin]
                    hold_time_minutes = (now - pos["entry_time"]) / 60
                    
                    # Get current PnL
                    pnl_pct = await self.check_position_pnl(coin)
                    
                    log.debug(f"📊 {coin}: +{pnl_pct:.1f}% | Hold: {hold_time_minutes:.1f}m")
                    
                    # PROFIT-TAKING RULES
                    # Exit early if we hit 50%+ AND position older than 2 mins
                    if pnl_pct >= 50 and hold_time_minutes > 2:
                        log.info(f"💰 PROFIT LOCK: {coin} at +{pnl_pct:.1f}%")
                        await self.execute_sell(coin)
                    
                    # Exit if we hit 200%+ (lottery win)
                    elif pnl_pct >= 200:
                        log.info(f"🎰 LOTTERY WIN: {coin} at +{pnl_pct:.1f}%")
                        await self.execute_sell(coin)
                    
                    # Stop loss at -25%
                    elif pnl_pct <= -25:
                        log.warning(f"🛑 STOP LOSS: {coin} at {pnl_pct:.1f}%")
                        await self.execute_sell(coin)
                    
                    # Hard exit after 15 minutes (time decay)
                    elif hold_time_minutes > 15:
                        log.info(f"⏱️  TIME EXIT: {coin} after 15 minutes")
                        await self.execute_sell(coin)
                
                # Save state periodically
                if now - last_state_save > 30:
                    try:
                        state = {
                            "ts": datetime.now().isoformat(),
                            "positions": len(self.positions),
                            "trades_seen": len(self.orangie_history),
                            "scan_num": scan_num,
                        }
                        with open(STATE_FILE, "w") as f:
                            json.dump(state, f)
                        last_state_save = now
                    except:
                        pass
                
                await asyncio.sleep(1)
            
            except KeyboardInterrupt:
                log.info("🛑 Shutting down...")
                break
            except Exception as e:
                log.error(f"Loop error: {e}")
                await asyncio.sleep(5)

async def main():
    trader = FOOMOTrader()
    await trader.monitor_loop()

if __name__ == "__main__":
    asyncio.run(main())
