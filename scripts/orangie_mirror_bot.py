#!/usr/bin/env python3
"""
ORANGIE MIRROR BOT v1 — Real-time copy-trading
Watches Orangie's FOMO trades, mirrors them on your account.
$15 bankroll safeguard — aggressive risk management.
"""

import json
import os
import sys
import time
import threading
import logging
import urllib.request
import urllib.error
import ssl
from datetime import datetime
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.expanduser("~/.hermes/orangie_mirror.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("orangie_mirror")

# ─── CONFIG ──────────────────────────────────────────────────────────────────
HOME = os.path.expanduser("~")
CONFIG_FILE = os.path.join(HOME, ".hermes/fomo_config.json")

# Load FOMO API key + wallet
try:
    with open(CONFIG_FILE) as f:
        config = json.load(f)
        FOMO_API_KEY = config.get("fomo_api_key")
        WALLET_PUBKEY = config.get("wallet_public_key")
        WALLET_PRIVKEY = config.get("wallet_private_key")
except Exception as e:
    log.error(f"Failed to load config: {e}")
    sys.exit(1)

FOMO_API_BASE = "https://api.fomoapi.io/v2"
ORANGIE_USERNAME = "orangie"

# Trade settings
BANKROLL_USD = 15.0
MAX_POSITION_USD = 5.0  # 33% risk per trade (conservative for $15)
MIN_PROFIT_PCT = 50.0   # Exit at +50% or more
STOP_LOSS_PCT = -20.0   # Cut losses at -20%
CHECK_INTERVAL = 5      # Check Orangie's posts every 5 seconds
MAX_OPEN_POSITIONS = 1  # Only 1 position at a time

# SSL (macOS cert fix)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ─── STATE ───────────────────────────────────────────────────────────────────
tracked_trades = {}  # mint -> {"entry_price", "entry_time", "orangie_entry_price"}
last_orangie_post = None
watched_mint = None

# ─── FOMO API CALLS ──────────────────────────────────────────────────────────

def api_call(endpoint, method="GET", data=None):
    """Generic FOMO API call."""
    url = f"{FOMO_API_BASE}{endpoint}?key={FOMO_API_KEY}"
    try:
        req = urllib.request.Request(url, method=method)
        if data:
            req.data = json.dumps(data).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.error(f"API error on {endpoint}: {e}")
        return None

def get_wallet_balance():
    """Get current SOL balance."""
    result = api_call(f"/wallet/balance?wallet={WALLET_PUBKEY}")
    if result and "balance" in result:
        return float(result["balance"])
    return 0.0

def get_token_price(mint):
    """Get current token price in SOL."""
    result = api_call(f"/token/price?mint={mint}")
    if result and "price" in result:
        return float(result["price"])
    return None

def buy_token(mint, amount_sol):
    """Execute a buy order."""
    payload = {
        "mint": mint,
        "amount_sol": amount_sol,
        "wallet": WALLET_PUBKEY,
    }
    result = api_call("/trade/buy", method="POST", data=payload)
    if result and result.get("success"):
        log.info(f"✅ BUY executed: {mint} ({amount_sol} SOL)")
        return result.get("tx_id")
    else:
        log.error(f"❌ BUY failed: {result}")
        return None

def sell_token(mint, amount_tokens):
    """Execute a sell order."""
    payload = {
        "mint": mint,
        "amount_tokens": amount_tokens,
        "wallet": WALLET_PUBKEY,
    }
    result = api_call("/trade/sell", method="POST", data=payload)
    if result and result.get("success"):
        log.info(f"✅ SELL executed: {mint} ({amount_tokens} tokens)")
        return result.get("tx_id")
    else:
        log.error(f"❌ SELL failed: {result}")
        return None

# ─── ORANGIE FEED MONITOR ────────────────────────────────────────────────────

def fetch_orangie_posts():
    """
    Fetch Orangie's recent FOMO posts.
    Parse for buy/sell signals.
    """
    try:
        # Attempt to fetch via FOMO API (if available)
        result = api_call(f"/user/posts?username={ORANGIE_USERNAME}&limit=5")
        if result and "posts" in result:
            return result["posts"]
    except Exception as e:
        log.warning(f"API fetch failed, fallback to placeholder: {e}")
    
    # Fallback: return empty (in production, we'd scrape the web UI)
    return []

def parse_trade_signal(post):
    """
    Extract buy/sell signals from Orangie's post.
    Look for mentions of token names, prices, conviction, etc.
    """
    text = post.get("text", "").lower()
    
    # Super simplified: if post mentions "buy" or "long", it's a buy signal
    # In production, use NLP or regex to extract actual mint addresses
    
    if "buy" in text or "long" in text:
        return {"action": "buy", "text": post.get("text")}
    elif "sell" in text or "exit" in text:
        return {"action": "sell", "text": post.get("text")}
    
    return None

# ─── POSITION MONITORING ─────────────────────────────────────────────────────

def check_positions():
    """Monitor open positions for profit-taking or stop-loss."""
    global tracked_trades
    
    for mint, trade in list(tracked_trades.items()):
        current_price = get_token_price(mint)
        if not current_price:
            continue
        
        entry_price = trade["entry_price"]
        gain_pct = ((current_price - entry_price) / entry_price) * 100
        
        log.info(f"📊 {mint}: {gain_pct:+.2f}% (entry: {entry_price}, current: {current_price})")
        
        # Profit-take at +50%
        if gain_pct >= MIN_PROFIT_PCT:
            log.warning(f"🎯 Profit target hit on {mint}: {gain_pct:.2f}%")
            sell_token(mint, trade.get("amount_tokens", 0))
            del tracked_trades[mint]
        
        # Stop-loss at -20%
        elif gain_pct <= STOP_LOSS_PCT:
            log.error(f"🔴 Stop-loss triggered on {mint}: {gain_pct:.2f}%")
            sell_token(mint, trade.get("amount_tokens", 0))
            del tracked_trades[mint]

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

def main_loop():
    """Main monitoring loop."""
    global last_orangie_post, watched_mint
    
    log.info(f"🚀 ORANGIE MIRROR BOT started (bankroll: ${BANKROLL_USD})")
    log.info(f"Wallet: {WALLET_PUBKEY}")
    
    while True:
        try:
            # Check wallet balance
            balance = get_wallet_balance()
            log.info(f"💰 Wallet balance: {balance} SOL")
            
            if balance < 0.05:
                log.critical(f"⚠️  Wallet balance too low ({balance} SOL). Stopping bot.")
                break
            
            # Fetch Orangie's latest posts
            posts = fetch_orangie_posts()
            if posts:
                latest = posts[0]
                post_id = latest.get("id")
                
                # Check if it's a new post
                if post_id != last_orangie_post:
                    log.info(f"📝 New Orangie post: {latest.get('text', '')[:100]}")
                    
                    # Parse for signal
                    signal = parse_trade_signal(latest)
                    if signal:
                        if signal["action"] == "buy" and len(tracked_trades) < MAX_OPEN_POSITIONS:
                            log.warning(f"🔔 BUY SIGNAL from Orangie! Text: {signal['text']}")
                            # TODO: Extract mint address from post, execute buy
                        elif signal["action"] == "sell":
                            log.warning(f"🔔 SELL SIGNAL from Orangie! Text: {signal['text']}")
                            # TODO: Exit all positions
                    
                    last_orangie_post = post_id
            
            # Monitor open positions
            check_positions()
            
            time.sleep(CHECK_INTERVAL)
        
        except Exception as e:
            log.exception(f"Error in main loop: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
        sys.exit(0)
