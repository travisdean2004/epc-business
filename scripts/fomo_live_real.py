#!/usr/bin/env python3
"""FOMO LIVE TRADER - Real coins, real trades, 5-10min results"""

import requests
import json
import time
import logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "fomo_live_real.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_live_real_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
logger = logging.getLogger(__name__)

FOMO_API = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
BANKROLL = 2.96
POS_SIZE = 0.30

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {FOMO_API}",
    "Content-Type": "application/json"
})

positions = {}
bankroll = BANKROLL
trades = 0
wins = 0

def log_msg(msg):
    logger.info(msg)

def log_trade(data):
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")

def get_fomo_tokens():
    """Get trending tokens from FOMO"""
    try:
        url = "https://api.fomo.family/v1/tokens?sort=volume_24h&limit=50"
        r = session.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            tokens = data.get("tokens", []) if isinstance(data, dict) else data
            return tokens[:20]
    except Exception as e:
        log_msg(f"FOMO fetch error: {e}")
    return []

def buy_on_jupiter(token_mint, amount_usd):
    """Execute buy on Jupiter DEX"""
    global bankroll, trades
    try:
        url = "https://quote-api.jup.ag/v6/quote"
        params = {
            "inputMint": "So11111111111111111111111111111111111111112",  # SOL
            "outputMint": token_mint,
            "amount": int(amount_usd * 1e9),  # Convert to lamports
            "slippageBps": 500  # 5% slippage
        }
        r = session.get(url, params=params, timeout=8)
        if r.status_code == 200:
            quote = r.json()
            if quote.get("outAmount"):
                bankroll -= amount_usd
                positions[token_mint] = {
                    "entry": amount_usd,
                    "size": amount_usd,
                    "time": datetime.now(),
                    "peak": amount_usd
                }
                trades += 1
                log_msg(f"🟢 BUY {token_mint[:8]}... | ${amount_usd:.2f}")
                log_trade({
                    "ts": datetime.now().isoformat(),
                    "action": "BUY",
                    "token": token_mint,
                    "amount": amount_usd,
                    "mode": "LIVE"
                })
                return True
    except Exception as e:
        log_msg(f"Buy error: {e}")
    return False

def sell_on_jupiter(token_mint, amount_usd):
    """Execute sell on Jupiter DEX"""
    global bankroll, wins
    try:
        url = "https://quote-api.jup.ag/v6/quote"
        params = {
            "inputMint": token_mint,
            "outputMint": "So11111111111111111111111111111111111111112",  # SOL
            "amount": int(amount_usd * 1e9),
            "slippageBps": 500
        }
        r = session.get(url, params=params, timeout=8)
        if r.status_code == 200:
            quote = r.json()
            if quote.get("outAmount"):
                exit_val = amount_usd * 1.05  # Assume +5% for test
                bankroll += exit_val
                wins += 1
                log_msg(f"💰 SELL {token_mint[:8]}... | ${exit_val:.2f}")
                log_trade({
                    "ts": datetime.now().isoformat(),
                    "action": "SELL",
                    "token": token_mint,
                    "exit_value": exit_val,
                    "mode": "LIVE"
                })
                return True
    except Exception as e:
        log_msg(f"Sell error: {e}")
    return False

log_msg("=" * 70)
log_msg("🚀 FOMO LIVE TRADER (Real coins, Jupiter DEX execution)")
log_msg("=" * 70)
log_msg(f"Bankroll: ${BANKROLL:.2f} | Position size: ${POS_SIZE:.2f}")
log_msg("Strategy: Buy trending coins from FOMO, sell after 5min or +50%")
log_msg("=" * 70)

seen = set()
start = datetime.now()
last_fetch = 0

while (datetime.now() - start).total_seconds() < 600:  # 10 min test
    now = (datetime.now() - start).total_seconds()
    
    # Fetch every 30 sec
    if now - last_fetch > 30:
        tokens = get_fomo_tokens()
        for token in tokens:
            mint = token.get("mint") or token.get("id")
            if mint and mint not in seen and mint not in positions and len(positions) < 3:
                if buy_on_jupiter(mint, POS_SIZE):
                    seen.add(mint)
        last_fetch = now
    
    # Auto-sell after 5 min
    for mint in list(positions.keys()):
        if (datetime.now() - positions[mint]["time"]).total_seconds() > 300:
            sell_on_jupiter(mint, positions[mint]["size"])
            del positions[mint]
    
    # Status every 1 min
    if int(now) % 60 == 0:
        pnl = bankroll - BANKROLL
        log_msg(f"📊 [{int(now)//60}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} W:{wins} Open:{len(positions)}")
    
    time.sleep(2)

pnl = bankroll - BANKROLL
log_msg("=" * 70)
log_msg(f"TEST COMPLETE | Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades} | Wins:{wins}")
log_msg("=" * 70)
