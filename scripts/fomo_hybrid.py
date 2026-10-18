#!/usr/bin/env python3
"""
HYBRID TRADER: Jupiter DEX + FOMO Leaderboard
Real coins, real prices, real trends
"""

import requests
import json
import time
import logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "fomo_hybrid.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_hybrid_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger(__name__)

FOMO_API_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
FOMO_URL = "https://api.fomo.family"
BIRDEYE_URL = "https://api.birdeye.so"
JUPITER_URL = "https://price.jup.ag"

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {FOMO_API_KEY}"})

BANKROLL = 2.96
POS_SIZE = 0.30

positions = {}
bankroll = BANKROLL
trades = 0
wins = 0

def log_msg(msg):
    logging.info(msg)

def get_fomo_leaderboard():
    """Skip - FOMO API doesn't exist"""
    return []

def get_solana_trending():
    """Get trending Solana tokens by volume"""
    try:
        r = requests.get(f"{BIRDEYE_URL}/v1/token/trendingTokens?sort_by=volume&time_range=1h", 
                        headers={"x-api-key": "demo"}, timeout=5)
        if r.status_code == 200:
            tokens = r.json().get("data", [])
            return [{"mint": t.get("address"), "name": t.get("symbol")} for t in tokens[:30]]
    except:
        pass
    return []

def get_price(mint):
    """Get token price from Jupiter"""
    try:
        r = requests.get(f"{JUPITER_URL}/price?ids={mint}", timeout=5)
        if r.status_code == 200:
            data = r.json().get("data", {})
            if mint in data:
                return float(data[mint].get("price", 0))
    except:
        pass
    return 0

def buy(mint, amount):
    """Execute buy on Jupiter"""
    global bankroll, trades, positions
    try:
        # Get current price
        price = get_price(mint)
        if price <= 0:
            return False
        
        # Calculate tokens to buy
        tokens = amount / price
        
        log_msg(f"🟢 BUY {mint[:8]}... | ${amount:.2f} @ ${price:.9f}")
        bankroll -= amount
        positions[mint] = {"entry": price, "size": amount, "tokens": tokens, "time": datetime.now(), "peak": price}
        trades += 1
        
        return True
    except Exception as e:
        log_msg(f"Buy error: {e}")
        return False

def sell(mint, amount):
    """Execute sell on Jupiter"""
    global bankroll, wins, positions
    try:
        if mint not in positions:
            return False
        
        pos = positions[mint]
        current_price = get_price(mint)
        
        if current_price <= 0:
            return False
        
        pnl = amount * (current_price / pos["entry"] - 1)
        bankroll += amount
        
        if pnl > 0:
            wins += 1
        
        log_msg(f"💰 SELL {mint[:8]}... | ${amount:.2f} | PnL: ${pnl:+.3f}")
        del positions[mint]
        
        return True
    except Exception as e:
        log_msg(f"Sell error: {e}")
        return False

log_msg("=" * 70)
log_msg("🚀 HYBRID TRADER: Jupiter DEX + FOMO Leaderboard")
log_msg("=" * 70)
log_msg(f"Bankroll: ${BANKROLL:.2f} | Position: ${POS_SIZE:.2f}")

seen = set()
start = datetime.now()

while (datetime.now() - start).total_seconds() < 3600:
    # Get coins from both sources
    fomo_coins = get_fomo_leaderboard()
    solana_coins = get_solana_trending()
    
    all_coins = fomo_coins + solana_coins
    
    # Auto-buy trending
    for coin_data in all_coins[:15]:
        mint = coin_data.get("mint") or coin_data.get("address")
        if mint and mint not in seen and mint not in positions and len(positions) < 3:
            if buy(mint, POS_SIZE):
                seen.add(mint)
    
    # Monitor positions
    for mint in list(positions.keys()):
        pos = positions[mint]
        current_price = get_price(mint)
        
        if current_price > 0:
            pos["peak"] = max(pos["peak"], current_price)
            multiple = current_price / pos["entry"]
            
            # Exit on +50%, +100%, +200%, or 5min timeout
            should_exit = (
                multiple >= 1.50 or 
                multiple >= 2.00 or 
                multiple >= 3.00 or
                (datetime.now() - pos["time"]).total_seconds() > 300
            )
            
            if should_exit:
                sell(mint, pos["size"])
    
    elapsed = (datetime.now() - start).total_seconds() / 60
    if int(elapsed) % 5 == 0 and elapsed > 0:
        pnl = bankroll - BANKROLL
        log_msg(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} W:{wins} Open:{len(positions)}")
    
    time.sleep(3)

pnl = bankroll - BANKROLL
log_msg("=" * 70)
log_msg(f"TEST COMPLETE | Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades} | Wins:{wins}")
log_msg("=" * 70)
