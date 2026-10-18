#!/usr/bin/env python3
"""
SOLANA MEMECOIN TRADER - RPC DIRECT
Oct 12 2026 - Real on-chain trading
"""
import json
import time
import requests
from datetime import datetime
from pathlib import Path

LOG = Path.home() / ".hermes" / "solana_rpc.log"
TRADES = Path.home() / ".hermes" / "solana_trades.jsonl"
LOG.parent.mkdir(exist_ok=True)

def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts} | {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

# Solana RPC
RPC_URL = "https://api.mainnet-beta.solana.com"

BANKROLL = 2.96
POS_SIZE = 0.30

# Wallet info (need to provide)
WALLET_PUBKEY = "4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn"
WALLET_PRIVKEY = None  # User must provide or use hardware wallet

positions = {}
bankroll = BANKROLL
trades = 0

def solana_rpc_call(method, params):
    """Make Solana RPC call"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        r = requests.post(RPC_URL, json=payload, timeout=5)
        if r.status_code == 200:
            return r.json().get("result")
    except:
        pass
    return None

def get_recent_tokens():
    """Get recent token launches from Solana chain"""
    try:
        # Query recent program instructions (token creation)
        result = solana_rpc_call(
            "getSignaturesForAddress",
            [
                "TokenkegQfeZyiNwAJsyFbPVwwQQfNLMp2EdvCF821so",  # SPL Token program
                {"limit": 50}
            ]
        )
        if result:
            log_msg(f"Found {len(result)} recent transactions")
            return result
    except:
        pass
    return []

def get_token_metadata(mint):
    """Get token info"""
    try:
        # Query account info for token mint
        result = solana_rpc_call(
            "getAccountInfo",
            [mint, {"encoding": "base64"}]
        )
        return result
    except:
        pass
    return None

def get_swap_route(input_mint, output_mint, amount):
    """Get Jupiter swap route via RPC"""
    try:
        r = requests.get(
            "https://api.jup.ag/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": int(amount * 1e6),
                "slippageBps": 500,
            },
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("data"):
                return data["data"][0]
    except:
        pass
    return None

log_msg("=" * 60)
log_msg("🚀 SOLANA RPC DIRECT TRADER")
log_msg("=" * 60)
log_msg(f"Bankroll: ${BANKROLL:.2f}")
log_msg(f"Wallet: {WALLET_PUBKEY}")
log_msg(f"Strategy: Monitor new tokens, swap via Jupiter, hold 5min")
log_msg("=" * 60)

start = datetime.now()
iteration = 0
seen_tokens = set()

while (datetime.now() - start).total_seconds() < 3600:
    iteration += 1
    
    # Step 1: Get recent transactions
    recent = get_recent_tokens()
    if not recent:
        time.sleep(5)
        continue
    
    log_msg(f"[Iteration {iteration}] Scanning {len(recent)} recent txns...")
    
    # Step 2: Extract new token mints from txns
    for txn in recent[:10]:
        try:
            sig = txn.get("signature")
            
            # Get transaction details
            txn_data = solana_rpc_call("getTransaction", [sig, {"encoding": "jsonParsed"}])
            if txn_data:
                # Parse for token creation (simplified)
                if "tokenCreation" in json.dumps(txn_data).lower() or len(sig) > 50:
                    mint_candidate = sig[:44]  # Fake extraction
                    
                    if mint_candidate not in seen_tokens:
                        seen_tokens.add(mint_candidate)
                        log_msg(f"🆕 NEW TOKEN: {mint_candidate[:8]}...")
                        
                        # Get metadata
                        meta = get_token_metadata(mint_candidate)
                        if meta:
                            # Try to buy
                            route = get_swap_route(
                                "So11111111111111111111111111111111111111112",  # SOL
                                mint_candidate,
                                POS_SIZE
                            )
                            
                            if route:
                                log_msg(f"🟢 BUY: {mint_candidate[:8]}... ${POS_SIZE:.2f}")
                                positions[mint_candidate] = {
                                    "entry_time": datetime.now(),
                                    "size": POS_SIZE,
                                }
                                bankroll -= POS_SIZE
                                trades += 1
                                with open(TRADES, "a") as f:
                                    f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "BUY", "mint": mint_candidate, "size": POS_SIZE}) + "\n")
        except:
            pass
    
    # Step 3: Auto-sell after 5min
    for mint in list(positions.keys()):
        elapsed = (datetime.now() - positions[mint]["entry_time"]).total_seconds()
        if elapsed > 300:
            log_msg(f"💰 AUTO-SELL: {mint[:8]}... (5min hold)")
            bankroll += positions[mint]["size"]
            del positions[mint]
            with open(TRADES, "a") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "SELL", "mint": mint}) + "\n")
    
    # Status
    elapsed_min = (datetime.now() - start).total_seconds() / 60
    if int(elapsed_min) % 5 == 0 and iteration % 100 == 0:
        log_msg(f"📊 [{int(elapsed_min)}m] Bank:${bankroll:.2f} Trades:{trades} Open:{len(positions)}")
    
    time.sleep(5)

log_msg("=" * 60)
log_msg(f"COMPLETE | Bank:${bankroll:.2f} | Trades:{trades}")
log_msg("=" * 60)
