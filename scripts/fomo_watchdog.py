#!/usr/bin/env python3
"""
FOMO BOT WATCHDOG - Monitor bot health and report trades
Runs every 2 minutes via cron
- Checks if bot is alive
- Restarts if crashed
- Monitors trades and sends alerts
"""

import json
import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

HOME = os.path.expanduser("~")
BOT_SCRIPT = os.path.join(HOME, ".hermes/scripts/fomo_orangie_live.py")
BOT_LOG = os.path.join(HOME, ".hermes/fomo_live.log")
TRADES_FILE = os.path.join(HOME, ".hermes/fomo_live_trades.jsonl")
STATE_FILE = os.path.join(HOME, ".hermes/fomo_watchdog_state.json")

def load_watchdog_state():
    """Load previously reported trades to avoid duplicates."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"last_trade_line": 0, "reported_trades": []}

def save_watchdog_state(state):
    """Save watchdog state."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def is_bot_running():
    """Check if fomo_orangie_live.py process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "fomo_orangie_live.py"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

def restart_bot():
    """Restart the bot process."""
    try:
        cmd = f"nohup python3 {BOT_SCRIPT} >> {BOT_LOG} 2>&1 &"
        subprocess.run(cmd, shell=True, check=False, timeout=10)
        time.sleep(2)  # Give it a moment to start
        return is_bot_running()
    except Exception as e:
        print(f"Failed to restart bot: {e}")
        return False

def read_new_trades():
    """Read new trades from the trades file."""
    state = load_watchdog_state()
    trades = []
    
    if not os.path.exists(TRADES_FILE):
        return trades, state
    
    try:
        with open(TRADES_FILE, 'r') as f:
            lines = f.readlines()
        
        # Get only new lines since last read
        start_line = state.get("last_trade_line", 0)
        new_lines = lines[start_line:]
        
        for line in new_lines:
            try:
                trade = json.loads(line.strip())
                trades.append(trade)
            except json.JSONDecodeError:
                pass
        
        # Update state
        state["last_trade_line"] = len(lines)
        save_watchdog_state(state)
        
    except Exception as e:
        print(f"Error reading trades: {e}")
    
    return trades, state

def format_trade_alert(trade):
    """Format a trade into an alert message."""
    try:
        coin = trade.get("coin", "UNKNOWN").upper()
        action = trade.get("action", "TRADE").upper()  # BUY or SELL
        size_usd = trade.get("size_usd", 0)
        pnl_pct = trade.get("pnl_pct", 0)
        
        if action == "BUY":
            emoji = "🟢"
            msg = f"{emoji} BUY {coin} | ${size_usd:.2f}"
        elif action == "SELL":
            emoji = "🟡"
            if pnl_pct >= 0:
                msg = f"{emoji} SELL {coin} | +{pnl_pct:.1f}%"
            else:
                msg = f"{emoji} SELL {coin} | {pnl_pct:.1f}%"
        else:
            msg = f"📊 {action} {coin} | ${size_usd:.2f}"
        
        return msg
    except Exception as e:
        return f"Trade alert (parse error: {e})"

def send_telegram_alert(message):
    """Send alert via Hermes telegram command."""
    try:
        # Try to send to Fomo Trading Chat if it exists, otherwise DM
        cmd = f'hermes telegram send --to "Fomo Trading Chat" "{message}" 2>/dev/null || hermes telegram send "{message}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception as e:
        print(f"Failed to send telegram: {e}")
        return False

def main():
    """Main watchdog loop."""
    # Check if bot is running
    if not is_bot_running():
        print(f"[{datetime.now().isoformat()}] Bot not running, attempting restart...")
        if restart_bot():
            print(f"[{datetime.now().isoformat()}] Bot restarted successfully")
        else:
            print(f"[{datetime.now().isoformat()}] ALERT: Failed to restart bot")
            send_telegram_alert("🚨 FOMO BOT DEAD - Failed to restart")
            return
    
    # Check for new trades
    trades, state = read_new_trades()
    
    if trades:
        print(f"[{datetime.now().isoformat()}] Found {len(trades)} new trade(s)")
        for trade in trades:
            alert = format_trade_alert(trade)
            print(f"[{datetime.now().isoformat()}] Sending: {alert}")
            send_telegram_alert(alert)
    else:
        # Silent - no new trades
        pass

if __name__ == "__main__":
    main()
