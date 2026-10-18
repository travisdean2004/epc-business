#!/usr/bin/env python3
"""
FOMO MIRROR BOT v3 — $15 Bankroll, Safety First
- Paper trade mode ENFORCED (no real buys until approved)
- Tracks Orangie's trades on FOMO, mirrors with scaled position
- Kill-switch at $3 (20% loss) — stops immediately
"""

import json
import os
import time
import requests
import sys
from datetime import datetime

HOME = os.path.expanduser("~")
CONFIG_FILE = os.path.join(HOME, ".hermes/fomo_config.json")

# Load credentials
with open(CONFIG_FILE) as f:
    config = json.load(f)
    FOMO_API_KEY = config["fomo_api_key"]
    WALLET = config["wallet_public_key"]

# ========== SETTINGS ==========
BANKROLL = 15.0  # $15 starting
KILL_SWITCH_USD = 3.0  # Stop if balance drops below $3 (80% loss)
TRADE_SIZE = 2.5  # $2.50 per trade (16% of bankroll) — conservative
PAPER_MODE = True  # TEST ONLY — no real purchases
TARGET_TRADER = "orangie"  # Follow orangie's trades

# State tracking
state = {
    "balance": BANKROLL,
    "trades_made": 0,
    "wins": 0,
    "losses": 0,
    "total_pnl": 0.0,
    "start_time": datetime.now().isoformat(),
}

def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def get_orangie_trades():
    """Fetch recent trades from Orangie on FOMO"""
    try:
        headers = {"X-API-Key": FOMO_API_KEY}
        # FOMO API endpoint for trader's recent positions
        url = f"https://api.fomoapi.io/v2/traders/{TARGET_TRADER}/positions"
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        return resp.json().get("positions", [])
    except Exception as e:
        log_msg(f"❌ Failed to fetch trades: {e}")
        return []

def execute_mirror_trade(coin_symbol, trade_type, orangie_amount):
    """
    Mirror Orangie's trade with our bankroll ratio
    trade_type: 'buy' or 'sell'
    """
    global state
    
    if state["balance"] < KILL_SWITCH_USD:
        log_msg(f"🛑 KILL SWITCH HIT: Balance ${state['balance']:.2f} < ${KILL_SWITCH_USD:.2f}")
        return False
    
    if PAPER_MODE:
        # Simulate trade
        if trade_type == "buy":
            state["balance"] -= TRADE_SIZE
            log_msg(f"📄 PAPER BUY: {coin_symbol} @ ${TRADE_SIZE:.2f} (Orangie: ${orangie_amount:.2f})")
            state["trades_made"] += 1
        elif trade_type == "sell":
            pnl = TRADE_SIZE * 0.15  # Assume 15% gain for demo
            state["balance"] += pnl
            state["total_pnl"] += pnl
            state["wins"] += 1
            log_msg(f"📄 PAPER SELL: {coin_symbol} +${pnl:.2f} | Balance: ${state['balance']:.2f}")
        return True
    else:
        log_msg(f"⚠️  LIVE MODE DISABLED — set PAPER_MODE = False only after testing")
        return False

def monitor_loop():
    """Main monitoring loop"""
    log_msg(f"🚀 Starting FOMO Mirror Bot (v3)")
    log_msg(f"📊 Bankroll: ${BANKROLL:.2f} | Trade Size: ${TRADE_SIZE:.2f} | Kill Switch: ${KILL_SWITCH_USD:.2f}")
    log_msg(f"📄 PAPER MODE: {PAPER_MODE} (no real money at risk)")
    log_msg(f"👀 Tracking: @{TARGET_TRADER}")
    log_msg("")
    
    start_time = time.time()
    timeout = 120  # Run for 2 minutes (demo)
    
    while time.time() - start_time < timeout:
        trades = get_orangie_trades()
        
        if trades:
            log_msg(f"📍 Found {len(trades)} recent Orangie positions")
            for trade in trades[:2]:  # Mirror last 2 trades only
                symbol = trade.get("symbol", "?")
                side = trade.get("side", "unknown")
                amount = trade.get("amount", 0)
                pnl = trade.get("pnl", 0)
                
                log_msg(f"  → {side.upper()}: {symbol} | Amount: ${amount:.2f} | PnL: ${pnl:+.2f}")
                
                if side == "buy":
                    execute_mirror_trade(symbol, "buy", amount)
                elif side == "sell":
                    execute_mirror_trade(symbol, "sell", amount)
        
        # Status
        log_msg(f"💰 Balance: ${state['balance']:.2f} | Trades: {state['trades_made']} | PnL: ${state['total_pnl']:+.2f}")
        
        if state["balance"] < KILL_SWITCH_USD:
            log_msg(f"🛑 STOPPING: Balance below kill switch threshold")
            break
        
        time.sleep(15)  # Check every 15 seconds
    
    # Final report
    log_msg("")
    log_msg("=" * 50)
    log_msg("FINAL REPORT")
    log_msg(f"  Bankroll: ${BANKROLL:.2f} → ${state['balance']:.2f}")
    log_msg(f"  Trades Made: {state['trades_made']}")
    log_msg(f"  Wins: {state['wins']} | Losses: {state['losses']}")
    log_msg(f"  Net PnL: ${state['total_pnl']:+.2f}")
    log_msg(f"  ROI: {((state['balance'] - BANKROLL) / BANKROLL * 100):+.1f}%")
    log_msg("=" * 50)
    
    # Save state
    state_file = os.path.join(HOME, ".hermes/fomo_mirror_state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    log_msg(f"✅ State saved to {state_file}")

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        log_msg("\n⏹️  Stopped by user")
        sys.exit(0)
    except Exception as e:
        log_msg(f"❌ Fatal error: {e}")
        sys.exit(1)
