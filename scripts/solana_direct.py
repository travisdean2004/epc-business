#!/usr/bin/env python3
"""
SOLANA RPC DIRECT TRADING BOT
Oct 12 2026 - No UI, no API wrapper, direct blockchain execution
"""
import requests
import json
import time
from datetime import datetime
from pathlib import Path
import base64
import hashlib

LOG = Path.home() / ".hermes" / "solana_direct.log"
TRADES = Path.home() / ".hermes" / "solana_direct_trades.jsonl"
LOG.parent.mkdir(exist_ok=True)

def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts} | {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

# Solana RPC
RPC = "https://api.mainnet-beta.solana.com"
# Public keypair (simulation mode - no real signing)
WALLET = "4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn"

# Major tokens
TOKENS = {
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixVqXgE4a8JRlKwgiKA",
    "WIF": "EKpQB2CdsBczWTbjciqj6wVsKvCWYDtiK7S4f5LTtWt",
    "PUMPKIN": "cJJznmP5QZxLqjLVVNqatfZ5s57nt2CYrTt4yW3fKPy",
    "POPCAT": "ipB9nUHQlewKh6K3FDpT3v6DnB7C3B3LoMm33Txbm6X",
}

def get_rpc_balance(pubkey):
    """Get SOL balance via RPC"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey]
        }
        r = requests.post(RPC, json=payload, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if "result" in data:
                return data["result"]["value"] / 1e9  # Convert lamports to SOL
    except:
        pass
    return None

def get_token_price(mint):
    """Get token price from Jupiter API"""
    try:
        url = f"https://api.coingecko.com/api/v3/simple/token_price/solana"
        params = {"contract_addresses": mint, "vs_currencies": "usd"}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if mint in data and "usd" in data[mint]:
                return data[mint]["usd"]
    except:
        pass
    return None

def simulate_trade(token_name, token_mint, amount_usd):
    """Simulate trade execution (no real signing)"""
    price = get_token_price(token_mint)
    if price and price > 0:
        tokens_bought = amount_usd / price
        return {"token": token_name, "price": price, "amount": tokens_bought, "entry_usd": amount_usd}
    return None

log_msg("=" * 70)
log_msg("🚀 SOLANA RPC DIRECT TRADING BOT")
log_msg("=" * 70)
log_msg(f"Wallet: {WALLET}")
log_msg(f"Bankroll: $2.96 | Position: $0.30")
log_msg(f"Strategy: Buy low-cap tokens, exit +50%/+100%/+200%")
log_msg("=" * 70)

bankroll = 2.96
positions = {}
trades = 0
wins = 0
start = datetime.now()

# Get initial balance
initial_bal = get_rpc_balance(WALLET)
if initial_bal:
    log_msg(f"Wallet balance: {initial_bal:.3f} SOL")

iteration = 0
while (datetime.now() - start).total_seconds() < 3600:
    iteration += 1
    
    # Scan top tokens for entry
    for token_name, token_mint in list(TOKENS.items()):
        if token_name not in positions:
            price = get_token_price(token_mint)
            
            if price and price > 0 and price < 1.0:  # Only buy sub-$1 tokens
                # Simulate buy
                trade = simulate_trade(token_name, token_mint, 0.30)
                if trade:
                    positions[token_name] = {
                        "entry_price": price,
                        "tokens": trade["amount"],
                        "entry_usd": 0.30,
                        "entry_time": datetime.now(),
                        "tiers_sold": [False, False, False],
                        "peak_price": price,
                    }
                    bankroll -= 0.30
                    trades += 1
                    log_msg(f"🟢 BUY {token_name}: $0.30 @ ${price:.6f} ({trade['amount']:.0f} tokens)")
                    with open(TRADES, "a") as f:
                        f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "BUY", "token": token_name, "price": price}) + "\n")
    
    # Monitor exits
    for token_name in list(positions.keys()):
        pos = positions[token_name]
        current_price = get_token_price(TOKENS[token_name])
        
        if current_price and current_price > 0:
            multiple = current_price / pos["entry_price"]
            
            # Track peak
            if current_price > pos["peak_price"]:
                pos["peak_price"] = current_price
            
            # Tier exits
            tiers = [1.50, 2.00, 3.00]
            for tier_idx, tier_mult in enumerate(tiers):
                if not pos["tiers_sold"][tier_idx] and multiple >= tier_mult:
                    exit_usd = pos["entry_usd"] * 0.25
                    pnl = exit_usd * (multiple - 1)
                    pos["tiers_sold"][tier_idx] = True
                    bankroll += exit_usd + pnl
                    wins += 1
                    log_msg(f"💰 SELL {token_name} TIER {tier_idx+1}: +{(multiple-1)*100:.0f}% | PnL: ${pnl:.3f}")
                    with open(TRADES, "a") as f:
                        f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "SELL", "token": token_name, "tier": tier_idx+1, "multiple": multiple}) + "\n")
            
            # All tiers sold
            if all(pos["tiers_sold"]):
                del positions[token_name]
        
        # Time exit (5 min)
        if (datetime.now() - pos["entry_time"]).total_seconds() > 300:
            if token_name in positions:
                del positions[token_name]
                log_msg(f"⏰ {token_name}: 5min timeout, exiting")
    
    # Status
    elapsed = (datetime.now() - start).total_seconds() / 60
    if int(elapsed) % 5 == 0 and iteration % 100 == 0:
        pnl = bankroll - 2.96
        log_msg(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} PnL:${pnl:+.2f} Trades:{trades} W:{wins} Open:{len(positions)}")
    
    time.sleep(3)

pnl = bankroll - 2.96
log_msg("=" * 70)
log_msg(f"FINAL: ${bankroll:.2f} | PnL: ${pnl:+.2f} | Trades: {trades} | Wins: {wins}")
log_msg("=" * 70)
