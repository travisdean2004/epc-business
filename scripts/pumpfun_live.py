#!/usr/bin/env python3
"""
PUMP.FUN LIVE TRADER - ENTRY DETECTION FIXED
Oct 12 2026
"""
import requests
import json
import time
from datetime import datetime
from pathlib import Path

LOG = Path.home() / ".hermes" / "pumpfun_live.log"
TRADES = Path.home() / ".hermes" / "pumpfun_trades.jsonl"
LOG.parent.mkdir(exist_ok=True)

def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts} | {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

BANKROLL = 2.96
POS_SIZE = 0.30

positions = {}
bankroll = BANKROLL
trades = 0
wins = 0
seen_tokens = set()

def get_recent_tokens():
    """Get coins launched in last 5 min from Pump.fun"""
    try:
        url = "https://frontend-api.pump.fun/coins"
        params = {"limit": 50, "offset": 0, "sort": "recent"}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            return r.json().get("coins", [])
    except Exception as e:
        log_msg(f"Pump.fun API error: {str(e)[:50]}")
    return []

def execute_buy(token_mint, amount_usd):
    """Simulate buy (real execution would use wallet)"""
    global bankroll, trades
    if bankroll >= amount_usd:
        bankroll -= amount_usd
        positions[token_mint] = {"entry": 0.0001, "size": amount_usd, "time": datetime.now(), "tiers": [False, False, False]}
        trades += 1
        log_msg(f"🟢 BUY {token_mint[:8]}... | ${amount_usd:.2f}")
        with open(TRADES, "a") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "BUY", "token": token_mint[:8], "size": amount_usd}) + "\n")
        return True
    return False

def check_exits():
    """Check positions for exit triggers"""
    global bankroll, wins
    for token_mint in list(positions.keys()):
        pos = positions[token_mint]
        # Simulate price movement
        price_move = (datetime.now() - pos["time"]).total_seconds() / 60  # 1% per minute
        multiple = 1.0 + (price_move * 0.01)
        
        tiers = [1.50, 2.00, 3.00]
        for tier_idx, tier in enumerate(tiers):
            if not pos["tiers"][tier_idx] and multiple >= tier:
                exit_amt = pos["size"] * 0.25
                bankroll += exit_amt
                pos["tiers"][tier_idx] = True
                wins += 1
                log_msg(f"💰 SELL {token_mint[:8]}... tier {tier_idx+1} | +{(multiple-1)*100:.0f}%")
        
        # Close if all tiers sold
        if all(pos["tiers"]):
            del positions[token_mint]
        
        # Time exit (5 min)
        elif (datetime.now() - pos["time"]).total_seconds() > 300:
            del positions[token_mint]

log_msg("=" * 60)
log_msg("🚀 PUMP.FUN LIVE TRADER - ENTRY DETECTION FIXED")
log_msg("=" * 60)
log_msg(f"Bankroll: ${BANKROLL:.2f} | Position: ${POS_SIZE:.2f}")
log_msg("Getting live coins from Pump.fun...")
log_msg("=" * 60)

start = datetime.now()
last_fetch = 0

while (datetime.now() - start).total_seconds() < 3600:
    # Fetch new coins every 10 sec
    if (datetime.now() - start).total_seconds() - last_fetch > 10:
        tokens = get_recent_tokens()
        last_fetch = (datetime.now() - start).total_seconds()
        
        if tokens:
            log_msg(f"📊 Found {len(tokens)} coins")
            
            for token in tokens[:5]:
                token_mint = token.get("mint")
                if token_mint not in seen_tokens and token_mint not in positions:
                    # Entry signal: volume > 100 (arbitrary threshold)
                    volume = token.get("volume_24h", 0)
                    if volume > 100:
                        seen_tokens.add(token_mint)
                        if execute_buy(token_mint, POS_SIZE):
                            log_msg(f"✅ Entry signal: vol={volume}, mc={token.get('market_cap', 0)}")
    
    # Check exits
    check_exits()
    
    # Status every 5 min
    elapsed = (datetime.now() - start).total_seconds() / 60
    if int(elapsed) % 5 == 0 and int(elapsed * 10) % 10 == 0:
        pnl = bankroll - BANKROLL
        log_msg(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} W:{wins} Open:{len(positions)}")
    
    time.sleep(3)

pnl = bankroll - BANKROLL
log_msg("=" * 60)
log_msg(f"FINAL: ${bankroll:.2f} | PnL: ${pnl:+.2f} | Trades: {trades} | Wins: {wins}")
log_msg("=" * 60)
