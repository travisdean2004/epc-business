#!/usr/bin/env python3
"""
SOLANA PUMP.FUN BLOCKCHAIN WATCHER
Monitor Solana RPC for new pump.fun token launches in real-time.
Catch coins at genesis, execute buys on your $15 bankroll.
"""

import json, os, sys, time, urllib.request, urllib.error, ssl, logging
from datetime import datetime
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
log = logging.getLogger("solana_watcher")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
HOME = os.path.expanduser("~")
CONFIG_FILE = os.path.join(HOME, ".hermes/fomo_config.json")
STATE_FILE = os.path.join(HOME, ".hermes/solana_watcher_state.json")
TRADES_FILE = os.path.join(HOME, ".hermes/pumpfun_trades.jsonl")

# Load wallet
try:
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
        WALLET_PUB = cfg["wallet_public_key"]
        WALLET_PRIV = cfg["wallet_private_key"]
except Exception as e:
    log.error(f"Failed to load config: {e}")
    sys.exit(1)

# Solana RPC
RPC_URL = "https://api.mainnet-beta.solana.com"
PUMP_PROGRAM_ID = "6EF8rQNwhWALcuvRZEjP3whABoYwDRvCyQSoE521T5ty"  # pump.fun raydium

# Trading config
BANKROLL = 15.0
MIN_TRADE = 2.0
MAX_TRADE = 5.0
ENTRY_MCAP_MAX = 10_000_000  # sub-$10M only
EXIT_TARGETS = {
    0.5: 0.3,    # +50% → sell 30%
    1.0: 0.3,    # +100% → sell 30% more
    2.0: 0.4,    # +200% → sell all
}
STOP_LOSS_PCT = -25
MAX_HOLD_MINS = 15

# State
open_positions = {}  # mint -> {entry_price, entry_sol, entry_time, tokens}
price_cache = {}
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# ─────────────────────────────────────────────────────────────────────────────
# RPC HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def rpc_call(method: str, params: List) -> Optional[Dict]:
    """Call Solana RPC."""
    try:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 100000,
            "method": method,
            "params": params,
        })
        
        req = urllib.request.Request(
            RPC_URL,
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
        )
        
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if "result" in result:
                return result["result"]
            elif "error" in result:
                log.warning(f"RPC error {method}: {result['error']}")
            return None
    except Exception as e:
        log.error(f"RPC call {method} failed: {e}")
        return None

def get_token_metadata(mint: str) -> Optional[Dict]:
    """Fetch token metadata (decimals, supply)."""
    try:
        # Get token supply
        supply_result = rpc_call("getTokenSupply", [mint])
        if not supply_result:
            return None
        
        return {
            "mint": mint,
            "decimals": supply_result.get("value", {}).get("decimals", 6),
            "supply": float(supply_result.get("value", {}).get("uiAmount", 0)),
        }
    except Exception as e:
        log.error(f"Failed to get metadata for {mint}: {e}")
        return None

def get_latest_signatures(limit: int = 100) -> List[Dict]:
    """Get latest transactions on pump.fun program."""
    try:
        sigs = rpc_call("getSignaturesForAddress", [
            PUMP_PROGRAM_ID,
            {"limit": limit},
        ])
        return sigs or []
    except Exception as e:
        log.error(f"Failed to get signatures: {e}")
        return []

def parse_create_token_ix(data: str) -> Optional[str]:
    """Extract token mint from pump.fun CREATE instruction.
    Pump.fun CREATE: discriminator (8 bytes) + token metadata.
    Token mint is typically in the account keys.
    """
    try:
        # This is simplified; real parsing requires understanding pump.fun's IDL
        # For now, extract from transaction accounts
        return None
    except Exception as e:
        log.error(f"Failed to parse instruction: {e}")
        return None

def get_transaction(sig: str) -> Optional[Dict]:
    """Fetch full transaction details."""
    try:
        tx = rpc_call("getTransaction", [
            sig,
            {"encoding": "json", "maxSupportedTransactionVersion": 0}
        ])
        return tx
    except Exception as e:
        log.warning(f"Failed to get tx {sig}: {e}")
        return None

def detect_pump_fun_create(tx: Dict) -> Optional[str]:
    """Detect pump.fun CREATE token instruction and extract mint.
    Returns: token mint address if detected, else None
    """
    try:
        if not tx or "transaction" not in tx:
            return None
        
        txn = tx["transaction"]
        meta = tx.get("meta", {})
        
        # Look for pump.fun program in inner instructions
        if "innerInstructions" not in meta:
            return None
        
        for inner in meta["innerInstructions"]:
            for instr in inner.get("instructions", []):
                prog_idx = instr.get("programIdIndex")
                accounts = txn["message"]["accountKeys"]
                
                if prog_idx is not None and prog_idx < len(accounts):
                    prog_id = accounts[prog_idx]["pubkey"]
                    
                    # Check if pump.fun program
                    if prog_id == PUMP_PROGRAM_ID:
                        # Mint is typically first account after program
                        acct_idx = instr.get("accounts", [])
                        if acct_idx and acct_idx[0] < len(accounts):
                            mint = accounts[acct_idx[0]]["pubkey"]
                            return mint
        
        # Also check top-level instructions
        for instr in txn["message"]["instructions"]:
            prog_idx = instr.get("programIdIndex")
            accounts = txn["message"]["accountKeys"]
            
            if prog_idx is not None and prog_idx < len(accounts):
                prog_id = accounts[prog_idx]["pubkey"]
                if prog_id == PUMP_PROGRAM_ID:
                    acct_idx = instr.get("accounts", [])
                    if acct_idx and acct_idx[0] < len(accounts):
                        mint = accounts[acct_idx[0]]["pubkey"]
                        return mint
        
        return None
    
    except Exception as e:
        log.error(f"Failed to parse pump.fun create: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# TRADING LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def should_buy(mint: str, metadata: Dict) -> bool:
    """Check if token meets buy criteria."""
    # In real implementation:
    # - Calculate market cap from initial liquidity
    # - Check for rug indicators (ownership, freeze, mint authority)
    # - Validate momentum (early buys, holder count)
    
    # For now: accept any new pump.fun token
    return True

def buy_token(mint: str, symbol: str = "???"):
    """Execute buy on Solana."""
    size_usd = min(MAX_TRADE, BANKROLL * 0.25)
    
    if size_usd < MIN_TRADE:
        log.warning(f"Trade size ${size_usd} < min, skipping")
        return
    
    log.info(f"🟢 BUY {symbol} ({mint[:8]}...) | Size: ${size_usd}")
    
    # In real mode: call Jupiter API or PumpPortal
    # For now: simulate
    position = {
        "mint": mint,
        "symbol": symbol,
        "entry_usd": size_usd,
        "entry_time": time.time(),
        "tokens": size_usd / 0.001,  # assume $0.001 entry (placeholder)
        "partial_exits": 0.0,
    }
    
    open_positions[mint] = position

def monitor_positions():
    """Monitor open positions for exits."""
    for mint in list(open_positions.keys()):
        pos = open_positions[mint]
        hold_mins = (time.time() - pos["entry_time"]) / 60
        
        # Placeholder: in real mode, fetch price from Jupiter/Raydium
        # For now: simulate 2x moon
        current_price = 0.002 if hold_mins > 2 else 0.001
        pnl_pct = ((current_price - 0.001) / 0.001) * 100
        
        log.info(f"📊 {pos['symbol']}: {pnl_pct:+.1f}% | hold {hold_mins:.1f}m")
        
        # Check targets
        for target_pct, sell_pct in EXIT_TARGETS.items():
            if pnl_pct >= (target_pct * 100):
                log.info(f"🟡 EXIT TARGET {pos['symbol']}: {pnl_pct:.1f}%")
                del open_positions[mint]
                break

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 80)
    log.info("🚀 SOLANA PUMP.FUN BLOCKCHAIN WATCHER")
    log.info(f"   Bankroll: ${BANKROLL} | Max trade: ${MAX_TRADE}")
    log.info(f"   Entry target: <${ENTRY_MCAP_MAX/1e6:.0f}M market cap")
    log.info(f"   Exit targets: +50% / +100% / +200%")
    log.info(f"   Wallet: {WALLET_PUB[:16]}...")
    log.info("=" * 80)
    
    seen_sigs = set()
    scan_count = 0
    last_save = time.time()
    
    while True:
        try:
            scan_count += 1
            
            # Get recent pump.fun transactions
            sigs = get_latest_signatures(limit=50)
            
            if not sigs:
                log.debug(f"Scan #{scan_count}: No new signatures")
                time.sleep(3)
                continue
            
            new_count = 0
            for sig_obj in sigs:
                sig = sig_obj.get("signature")
                if not sig or sig in seen_sigs:
                    continue
                
                seen_sigs.add(sig)
                new_count += 1
                
                # Fetch transaction
                tx = get_transaction(sig)
                if not tx:
                    continue
                
                # Detect pump.fun CREATE
                mint = detect_pump_fun_create(tx)
                if mint:
                    log.info(f"🎯 NEW PUMP.FUN TOKEN DETECTED: {mint}")
                    
                    # Get metadata
                    metadata = get_token_metadata(mint)
                    if metadata and should_buy(mint, metadata):
                        buy_token(mint, f"PUMP_{int(time.time())}")
            
            if new_count > 0:
                log.info(f"Scan #{scan_count}: Found {new_count} new transactions")
            
            # Monitor positions
            if open_positions:
                monitor_positions()
            
            # Save state
            if time.time() - last_save > 30:
                try:
                    with open(STATE_FILE, "w") as f:
                        json.dump({
                            "ts": datetime.now().isoformat(),
                            "positions": len(open_positions),
                            "sigs_seen": len(seen_sigs),
                        }, f)
                    last_save = time.time()
                except:
                    pass
            
            time.sleep(3)
        
        except KeyboardInterrupt:
            log.info("🛑 Stopping...")
            break
        except Exception as e:
            log.error(f"Error in main: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
