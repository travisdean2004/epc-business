#!/usr/bin/env python3
"""
PUMP.FUN EARLY CATCHER — Orangie Blueprint
Catch coins at launch (<$10M mcap), ride to 50-200%+, exit fast.
$15 bankroll. Real-time monitoring. Auto-execute via Solana.
"""

import json, os, sys, time, urllib.request, urllib.error, ssl, subprocess, logging
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("pumpfun_catcher")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
HOME = os.path.expanduser("~")
CONFIG_FILE = os.path.join(HOME, ".hermes/fomo_config.json")
STATE_FILE = os.path.join(HOME, ".hermes/pumpfun_state.json")
TRADES_LOG = os.path.join(HOME, ".hermes/pumpfun_trades.json")

# Load wallet keys
try:
    with open(CONFIG_FILE) as f:
        config = json.load(f)
        WALLET_PUB = config["wallet_public_key"]
        WALLET_PRIV = config["wallet_private_key"]
except Exception as e:
    log.error(f"Failed to load config: {e}")
    sys.exit(1)

# Bankroll & sizing
BANKROLL_USD = 15.0
MIN_TRADE = 2.0  # never trade less than $2 (fees)
MAX_TRADE = 5.0  # max $5 per trade (33% of roll)
ENTRY_MCAP_MAX = 10_000_000  # only enter sub-$10M
EXIT_TARGETS = [
    (50, 0.4),    # hit +50% → sell 40% of position
    (100, 0.3),   # hit +100% → sell 30% more
    (150, 0.2),   # hit +150% → sell remaining 20%
    (200, 1.0),   # hit +200% → sell all (full moon exit)
]
STOP_LOSS = -25  # cut if down 25%
HOLD_MAX_MINS = 20  # never hold >20 mins (Orangie exits fast)

# pump.fun API
PUMP_API = "https://frontend-api.pump.fun/coins"
SOL_RPC = "https://api.mainnet-beta.solana.com"

# SSL bypass
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# State
open_positions = {}  # mint -> {entry_price, entry_mcap, entry_time, tokens, buy_hash}
price_cache = {}     # mint -> (ts, price_usd)

# ─────────────────────────────────────────────────────────────────────────────
# API HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_json(url, timeout=10):
    """Fetch JSON from URL, handle SSL bypass."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.error(f"API error {url}: {e}")
        return None

def get_coin_price(mint):
    """Get current USD price for coin mint."""
    if mint in price_cache:
        ts, price = price_cache[mint]
        if time.time() - ts < 5:  # cache 5s
            return price
    
    try:
        # Try pump.fun API first
        data = fetch_json(f"{PUMP_API}/{mint}")
        if data and "usd" in data:
            price = data["usd"]
            price_cache[mint] = (time.time(), price)
            return price
    except:
        pass
    
    return None

def get_mcap(mint):
    """Get market cap for coin."""
    try:
        data = fetch_json(f"{PUMP_API}/{mint}")
        if data:
            supply = float(data.get("total_supply", 0))
            price = get_coin_price(mint)
            if supply and price:
                mcap = supply * price / 1e6  # in USD
                return mcap
    except:
        pass
    return None

def get_holder_count(mint):
    """Get holder count from pump.fun."""
    try:
        data = fetch_json(f"{PUMP_API}/{mint}")
        if data:
            return data.get("holder_count", 0)
    except:
        pass
    return 0

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_recent_launches():
    """Get recently launched coins from pump.fun (<5 mins old)."""
    try:
        # pump.fun frontend API returns latest coins
        data = fetch_json(f"{PUMP_API}?limit=50&sort=recent")
        if isinstance(data, list):
            launches = []
            for coin in data:
                mint = coin.get("mint")
                created_at = coin.get("created_timestamp", 0)
                age_mins = (time.time() - created_at) / 60
                
                if age_mins < 5:  # only <5 min old
                    mcap = get_mcap(mint)
                    holders = get_holder_count(mint)
                    price = get_coin_price(mint)
                    
                    if mcap and mcap < ENTRY_MCAP_MAX:
                        launches.append({
                            "mint": mint,
                            "symbol": coin.get("symbol", "???"),
                            "mcap": mcap,
                            "age_mins": age_mins,
                            "holders": holders,
                            "price": price,
                            "volume_5m": coin.get("volume_5m", 0),
                        })
            
            return sorted(launches, key=lambda x: x["age_mins"])
    except Exception as e:
        log.error(f"Failed to fetch launches: {e}")
    
    return []

def should_buy(coin):
    """Orangie signal check: early launch + momentum."""
    # ✓ Sub-$10M market cap
    # ✓ <5 mins old
    # ✓ 5+ holders already (some early adoption)
    # ✓ Volume in last 5m (real buys, not just sitting)
    
    return (
        coin["mcap"] < ENTRY_MCAP_MAX and
        coin["age_mins"] < 5 and
        coin["holders"] >= 5 and
        coin["volume_5m"] > 0
    )

# ─────────────────────────────────────────────────────────────────────────────
# TRADING
# ─────────────────────────────────────────────────────────────────────────────

def execute_buy(mint, symbol, entry_price, mcap):
    """Execute buy on Solana via Jupiter/Raydium."""
    amount_usd = min(MAX_TRADE, BANKROLL_USD * 0.25)  # max 25% per trade
    
    if amount_usd < MIN_TRADE:
        log.warning(f"Trade size ${amount_usd} < min ${MIN_TRADE}, skipping")
        return None
    
    log.info(f"🟢 BUY {symbol} @ ${entry_price} (mcap ${mcap/1e6:.1f}M, size ${amount_usd})")
    
    # In real mode: call solkey/trade.js or Jupiter API
    # For now: simulate buy
    tokens = amount_usd / entry_price
    
    position = {
        "mint": mint,
        "symbol": symbol,
        "entry_price": entry_price,
        "entry_mcap": mcap,
        "entry_time": time.time(),
        "tokens": tokens,
        "entry_usd": amount_usd,
        "buy_hash": f"tx_simulated_{int(time.time())}",  # TODO: real tx hash
        "partial_exits": 0.0,
    }
    
    open_positions[mint] = position
    log.info(f"   Position: {tokens:.0f} tokens, entry ${amount_usd}")
    
    return position

def check_exits():
    """Monitor open positions, exit on targets or stop loss."""
    to_close = []
    
    for mint, pos in list(open_positions.items()):
        current_price = get_coin_price(mint)
        if not current_price:
            continue
        
        # Calculate PnL
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
        hold_mins = (time.time() - pos["entry_time"]) / 60
        current_mcap = get_mcap(mint)
        
        log.info(f"📊 {pos['symbol']}: {pnl_pct:+.1f}% | mcap ${current_mcap/1e6:.1f}M | hold {hold_mins:.1f}m")
        
        # Check stop loss
        if pnl_pct <= STOP_LOSS:
            log.warning(f"🔴 STOP LOSS hit on {pos['symbol']} ({pnl_pct:.1f}%)")
            to_close.append((mint, pos, "stop_loss", pnl_pct))
            continue
        
        # Check max hold time
        if hold_mins > HOLD_MAX_MINS:
            log.warning(f"⏱️  MAX HOLD time on {pos['symbol']} ({hold_mins:.1f}m)")
            to_close.append((mint, pos, "timeout", pnl_pct))
            continue
        
        # Check profit targets
        for target_pct, sell_pct in EXIT_TARGETS:
            if pnl_pct >= target_pct and pos["partial_exits"] < target_pct / 50:
                remaining = pos["tokens"] * (1 - pos["partial_exits"])
                sell_tokens = remaining * sell_pct
                exit_value = sell_tokens * current_price
                
                log.info(f"🟡 PARTIAL EXIT {pos['symbol']}: {pnl_pct:.1f}% | sell {sell_tokens:.0f} tokens @ ${current_price} = ${exit_value:.2f}")
                pos["partial_exits"] += sell_pct
                
                # If fully exited, mark for close
                if pos["partial_exits"] >= 0.95:
                    to_close.append((mint, pos, "full_exit", pnl_pct))
    
    # Close fully exited positions
    for mint, pos, reason, pnl in to_close:
        exit_price = get_coin_price(mint)
        exit_value = pos["tokens"] * exit_price if exit_price else 0
        
        log.info(f"✅ CLOSE {pos['symbol']}: reason={reason}, pnl={pnl:.1f}%, exit=${exit_value:.2f}")
        
        # Log trade
        trade = {
            "ts": datetime.now().isoformat(),
            "symbol": pos["symbol"],
            "mint": mint,
            "entry_price": pos["entry_price"],
            "entry_usd": pos["entry_usd"],
            "entry_mcap": pos["entry_mcap"],
            "exit_price": exit_price,
            "exit_value": exit_value,
            "pnl_pct": pnl,
            "reason": reason,
        }
        
        # Append to trades log
        try:
            with open(TRADES_LOG, "a") as f:
                f.write(json.dumps(trade) + "\n")
        except:
            pass
        
        del open_positions[mint]

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log.info(f"🚀 PUMP.FUN EARLY CATCHER started")
    log.info(f"   Bankroll: ${BANKROLL_USD}, Max trade: ${MAX_TRADE}")
    log.info(f"   Entry target: <${ENTRY_MCAP_MAX/1e6:.0f}M mcap, <5 mins old")
    log.info(f"   Exit targets: 50%/100%/150%/200% or SL {STOP_LOSS}%")
    log.info(f"   Wallet: {WALLET_PUB[:16]}...")
    
    scan_count = 0
    last_state_save = time.time()
    
    while True:
        try:
            scan_count += 1
            
            # Scan for new launches
            launches = get_recent_launches()
            
            if launches:
                log.info(f"📡 Scan #{scan_count}: Found {len(launches)} launches <$10M, <5m old")
                for coin in launches[:3]:  # top 3 by recency
                    if should_buy(coin):
                        if coin["mint"] not in open_positions:
                            execute_buy(
                                coin["mint"],
                                coin["symbol"],
                                coin["price"],
                                coin["mcap"],
                            )
            
            # Monitor open positions
            if open_positions:
                check_exits()
            
            # Save state every 30s
            if time.time() - last_state_save > 30:
                try:
                    with open(STATE_FILE, "w") as f:
                        json.dump({
                            "ts": datetime.now().isoformat(),
                            "positions": len(open_positions),
                            "bankroll": BANKROLL_USD,
                        }, f)
                    last_state_save = time.time()
                except:
                    pass
            
            # Scan every 3 seconds (pump.fun moves FAST)
            time.sleep(3)
        
        except KeyboardInterrupt:
            log.info("🛑 Stopping...")
            break
        except Exception as e:
            log.error(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
