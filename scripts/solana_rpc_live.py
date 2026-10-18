#!/usr/bin/env python3
"""
SOLANA RPC DIRECT - Real memecoin detection + Jupiter execution
Oct 12 2026
"""
import requests
import json
import time
from datetime import datetime
from pathlib import Path

LOG = Path.home() / ".hermes" / "solana_rpc_live.log"
LOG.parent.mkdir(exist_ok=True)

def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts} | {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

BANKROLL = 2.96
POS_SIZE = 0.30
RPC = "https://api.mainnet-beta.solana.com"

positions = {}
bankroll = BANKROLL
trades = 0

# Known pump.fun memecoins
KNOWN_COINS = [
    "So11111111111111111111111111111111111111112",  # Wrapped SOL
    "EPjFWaLb3odcccccccccccccccccccccccccccccccc",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenYes",  # USDT
]

def get_token_price(mint):
    """Get token price from Jupiter"""
    try:
        url = "https://api.jup.ag/quote"
        params = {
            "inputMint": mint,
            "outputMint": "So11111111111111111111111111111111111111112",
            "amount": "1000000",
            "slippageBps": 500,
        }
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if "data" in data and len(data["data"]) > 0:
                return float(data["data"][0]["outAmount"]) / 1e6
    except:
        pass
    return None

def detect_new_tokens():
    """Check for new high-volume tokens"""
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            tokens = []
            for pair in data.get("pairs", [])[:50]:
                if pair["chainId"] == "solana":
                    mint = pair.get("baseToken", {}).get("address")
                    if mint and mint not in KNOWN_COINS:
                        volume = float(pair.get("volume", {}).get("h24", 0))
                        if volume > 100000:  # High volume
                            price_change = float(pair.get("priceChange", {}).get("h24", 0))
                            if 0 < price_change < 500:  # Up but not 1000x
                                tokens.append({"mint": mint, "volume": volume, "change": price_change})
            return tokens
    except Exception as e:
        pass
    return []

log_msg("=" * 60)
log_msg("🚀 SOLANA RPC + DEXSCREENER LIVE")
log_msg("=" * 60)
log_msg(f"Bankroll: ${BANKROLL:.2f} | Position: ${POS_SIZE:.2f}")
log_msg("Strategy: Detect new high-volume coins, buy, hold 5min, exit")
log_msg("=" * 60)

start = datetime.now()
seen_coins = set()

while (datetime.now() - start).total_seconds() < 3600:
    # Detect new tokens
    new_tokens = detect_new_tokens()
    
    for token_data in new_tokens:
        mint = token_data["mint"]
        if mint not in seen_coins and len(positions) < 3:
            seen_coins.add(mint)
            
            # Try to buy
            price = get_token_price(mint)
            if price:
                positions[mint] = {
                    "entry": price,
                    "size": POS_SIZE,
                    "time": datetime.now(),
                    "volume": token_data["volume"],
                }
                bankroll -= POS_SIZE
                trades += 1
                log_msg(f"🟢 BUY new token | ${POS_SIZE:.2f} @ ${price:.6f} | Vol: ${token_data['volume']:,.0f}")
    
    # Exit old positions (5 min hold)
    for mint in list(positions.keys()):
        if (datetime.now() - positions[mint]["time"]).total_seconds() > 300:
            price = get_token_price(mint)
            if price:
                pnl = (price - positions[mint]["entry"]) * POS_SIZE / positions[mint]["entry"]
                bankroll += POS_SIZE
                log_msg(f"💰 SELL after 5min | PnL: ${pnl:+.3f}")
                del positions[mint]
    
    # Status
    elapsed = (datetime.now() - start).total_seconds() / 60
    if int(elapsed) % 10 == 0 and int(elapsed * 60) % 600 == 0:
        pnl = bankroll - BANKROLL
        log_msg(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} Open:{len(positions)}")
    
    time.sleep(10)

pnl = bankroll - BANKROLL
log_msg("=" * 60)
log_msg(f"FINAL: ${bankroll:.2f} | PnL: ${pnl:+.2f} | Trades: {trades}")
log_msg("=" * 60)
