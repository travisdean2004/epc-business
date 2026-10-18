#!/usr/bin/env python3
import requests
import json
import time
import logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "fomo_aggressive_live.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_aggressive_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger(__name__)

FOMO_API_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
BASE_URL = "https://api.fomo.family"

BANKROLL = 2.96
POS_SIZE = 0.30

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {FOMO_API_KEY}"})

positions = {}
bankroll = BANKROLL
trades = 0
wins = 0

def log_trade(data):
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")

def get_trending():
    try:
        r = session.get(f"{BASE_URL}/tokens/trending", timeout=5)
        return r.json().get("tokens", [])[:20]
    except:
        return []

def buy(coin, amount):
    global bankroll, trades
    try:
        r = session.post(f"{BASE_URL}/trades/buy", json={"tokenMint": coin, "amountUSD": amount, "slippage": 5}, timeout=10)
        if r.status_code == 200:
            bankroll -= amount
            positions[coin] = {"entry": 0.0001, "size": amount, "time": datetime.now()}
            trades += 1
            log(f"🟢 BUY {coin[:8]}... ${amount}")
            log_trade({"ts": datetime.now().isoformat(), "action": "BUY", "coin": coin, "size": amount})
            return True
    except:
        pass
    return False

def sell(coin, amount):
    global bankroll, wins
    try:
        r = session.post(f"{BASE_URL}/trades/sell", json={"tokenMint": coin, "amountUSD": amount, "slippage": 5}, timeout=10)
        if r.status_code == 200:
            bankroll += amount
            wins += 1
            log(f"💰 SELL {coin[:8]}... ${amount}")
            log_trade({"ts": datetime.now().isoformat(), "action": "SELL", "coin": coin, "size": amount})
            return True
    except:
        pass
    return False

def log(msg):
    logging.info(msg)

log("=" * 60)
log("🔥 AGGRESSIVE 1HR TEST (Auto-buy trending, hold 5min, auto-sell)")
log("=" * 60)

seen = set()
start = datetime.now()

while (datetime.now() - start).total_seconds() < 3600:
    trending = get_trending()
    
    for token in trending:
        coin = token.get("mint")
        if coin not in seen and coin not in positions and len(positions) < 3:
            if buy(coin, POS_SIZE):
                seen.add(coin)
    
    # Auto-sell after 5 min
    for coin in list(positions.keys()):
        if (datetime.now() - positions[coin]["time"]).total_seconds() > 300:
            sell(coin, positions[coin]["size"])
            del positions[coin]
    
    elapsed = (datetime.now() - start).total_seconds() / 60
    if int(elapsed) % 5 == 0 and int(elapsed * 60) % 300 == 0:
        pnl = bankroll - BANKROLL
        log(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} W:{wins} Open:{len(positions)}")
    
    time.sleep(2)

pnl = bankroll - BANKROLL
log(f"FINAL: ${bankroll:.2f} | PnL: ${pnl:+.2f} | Trades: {trades} | Wins: {wins}")
log("=" * 60)
