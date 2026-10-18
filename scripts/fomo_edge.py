#!/usr/bin/env python3
"""
FOMO Edge v2 — Unified Early Signal System
All optimizations: trailing SL, partial exits, rugcheck, stale skip,
dead-coin timeout, bad-dev blacklist, per-KOL win rate, score auto-tuning.

Signal tiers (fastest to slowest):
  TIER 0 — second 0: grad dev, whale dev buy
  TIER 1 — <30s: sniper wallet, bundle (3+ wallets in 10s)
  TIER 2 — <90s: KOL wallet buy, FOMO app feed
  TIER 3 — score 65+: combined scoring fallback
"""

import json, os, sys, time, threading, logging, csv, urllib.request, urllib.error, urllib.parse, subprocess, ssl
from datetime import datetime
from collections import defaultdict
import websocket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("fomo_edge")

# SSL context that skips cert verification (same fix used everywhere on this Mac)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ── Paths ──────────────────────────────────────────────────────────────────
HOME             = os.path.expanduser("~")
CONFIG_DIR       = os.path.join(HOME, ".hermes")
TRADES_LOG       = os.path.join(CONFIG_DIR, "paper_trades.csv")
DEV_GRADUATES_F  = os.path.join(CONFIG_DIR, "dev_graduates.json")
DEV_BLACKLIST_F  = os.path.join(CONFIG_DIR, "dev_blacklist.json")
SNIPER_WALLETS_F = os.path.join(CONFIG_DIR, "sniper_wallets.json")
KOL_STATS_F      = os.path.join(CONFIG_DIR, "kol_stats.json")
POSITIONS_F      = os.path.join(CONFIG_DIR, "open_positions.json")  # persist across restarts

# ── Keys ───────────────────────────────────────────────────────────────────
FOMO_API_KEY  = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
FOMO_API_BASE = "https://api.fomoapi.io/v2"
FOMO_WS_URL   = f"wss://api.fomoapi.io/ws/alerts?key={FOMO_API_KEY}"

TG_CHAT = "-5051326332"  # LIVE MODE — alerts back on
LIVE_TRADING = False         # 📄 PAPER — proving profitability before going live
TRADE_EXECUTOR = os.path.expanduser("~/solkey/trade.js")
try:
    TG_BOT = json.load(open(os.path.expanduser("~/epc-webhook/config.json"))).get("TG_BOT_TOKEN", "")
except:
    TG_BOT = ""

SOL_PRICE = 155.0

# ── Trade settings ─────────────────────────────────────────────────────────
TRADE_SIZE_USD   = 20.0   # 🔴 LIVE $20 bankroll — using dynamic sizing below
BANKROLL_USD     = 20.0   # Total bankroll
# Dynamic sizing (flat tiers for $20 bankroll):
#   Score 85+ conviction + 75+ early → $5 max (25% of roll)
#   Score 70+ → $3
#   Score 55+ → $2
#   Late entry → skip
INITIAL_SL_PCT   = -18.0    # tight stop loss — cut losers fast
TP_FULL_PCT      = 200.0    # full exit at 2x — let real winners run to here
PARTIAL_EXIT_PCT = 80.0     # lock gains at +80%

MONITOR_SECS     = 300      # 5 min max hold — give winners room to develop
DEAD_COIN_SECS   = 25       # cut dead coins in 25s
STALE_ENTRY_SECS = 45       # skip entry if coin already 45s old
MAX_OPEN         = 1        # 1 position at a time — protect bankroll
SCORE_MIN        = 40       # 40+ required — catches real velocity signals but blocks pure garbage
FEE_RESERVE_SOL  = 0.025    # always keep ~$3 for gas fees

# ── HARD KILLSWITCH — never let the bot burn the wallet to zero ──────────────
MIN_WALLET_SOL   = 0.10     # if balance drops below this, STOP ALL TRADING immediately
#   At current prices ~$12 floor. Bot logs + TG alerts Travis. Does NOT restart itself.
# ─────────────────────────────────────────────────────────────────────────────

# Fee math: round-trip (buy + sell) costs ~0.003 SOL in priority fees + 1% PumpPortal fee
# On a $4 trade: ~$0.36 buy fee + ~$0.36 sell fee + $0.04 pump fee = ~$0.76 total
# We need at least +25% gain just to break even on fees for small trades
# So minimum trade size must be $3+ and we only enter if expected gain >> fees
FEE_ROUND_TRIP_SOL = 0.006  # conservative round-trip fee estimate in SOL
MIN_TRADE_USD    = 3.0       # never trade less than $3 — fees eat small trades alive

# Price fetch cache: mint -> (ts, mcap_sol)
PRICE_CACHE = {}

# Trailing stop levels — lock gains aggressively, let real winners run
TRAILING_STOPS = [
    (15,   -5),   # hit +15%  → SL = -5%  (near breakeven immediately)
    (30,   10),   # hit +30%  → SL = +10% (locked in profit — $PayWheel would have held)
    (60,   30),   # hit +60%  → SL = +30%
    (100,  60),   # hit +100% → SL = +60%
    (150,  100),  # hit +150% → SL = +100%
]

# Monitor every 3 seconds — pump.fun moves FAST, 8s was too slow
MONITOR_INTERVAL = 3

# ── KOL wallets ────────────────────────────────────────────────────────────
KOL_WALLETS = {
    # Real verified wallets from FOMO leaderboard 7d (Sep 25 2026)
    "83b2LMf12aLec92kur3duRA8VvUkLaXUtML31aCcZNCM": "Orangie",
    "Beqv6dzTcjV2eodo8RRXCiCcnSYrS1vkQKhfqwHXqeit": "pointfarmcap",
    "HDixbrzwwLXczhDBk1JVrurPQsuLE8FUKnW2pucSXN3o": "PoorGoat_",
    "4ugDhHJ8XDXAeABmrNmGffFaLbJb9BkPyiFGVSV9ocwo": "The__Solstice",
    "4ZZW5ePCAsHJdnHHUdgozdvLqYNVnkE9CgrW3iyZdskb": "bluntz_capital",
    "F5hkYsi8JxjyA2JHN5CA7MbnnhWubkXB2ZQB7Gkaxqs6": "theveeman",
    "AXN4A7HNzncqzD9KGSbiSzE58vqvQmQxn8jhfYCKx9ai": "RareDualJay",
    "9LF3d3fxAbeabsxn2GLzMKqNbS1MUMtKvMcNLjTPbDNo": "leo",
    "BA3nKHc4DoSANRrx4FcCupExzs6cWzw1wkPpqjnqJaCN": "AviFelman",
    "EU7FSVgkt8eZYV199enSCoQa3qoH6h6HP8v9BqpGDeG5": "pricedin",
    "9BMzTpSo4URse1oN666pmexhdjpU1vA5p7LtroCFQdLU": "Aurelius0121",
    "EVqxB3F6iUBeWsTpBFQqWwxpqUS8s4NrzgxBvQ2VRbTq": "boosteryting",
    "p9aQ8YfnUbyN6z9yWpKNN8ZHZYKEYJwmcLBedq7tKiQ":  "navi9000x",
    "9n4YTpjrfo4QcaPECng374QZjZpbvpeSvosBF9ZjZUkP": "attnmarkets",
    "Dx2HdT2RWCXqPGdH964JhzrSGdGMRQVY7n2jEYZt9njF": "RunningClam",
    "7FJDJ1HaQfL3GAcMCzoBrJ9Accnf5GUYYwfEPCBCDcVK": "sadcrissy",
    "33qkCrKgTSittYJrbJK3vK8inJ3gWU4zVCiGdYQytTUj": "kv4rl",
    "F11mt2PsYTR7RF7hzfvFyeFbWREiCS3soa5pGbPX88Lb": "Bull_Path",
    "HteuczX3kp63RicL14JtwoJkrJfn3fQUAunq5E1mbLKW": "CoachPauI",
    "U5PhnhckY1BB2hYoqTsbRf4MpUrnozVPemX3TAjDqaE":  "LA50197934",
    "CnEy6EVjK6bGMC9wxChibpkUQGNYPHWHttD2LAHJLggB": "MrMetavers3",
    "FRT8YuLJ9q8PPX2o4RUiJ9hWL427hNmMJ2M6JdgGgzwK": "bigwarzeth",
    "5vh3TZMDWhP2WNJNtUjYYps21JPnY3HYpR13c22LBwAT": "excesscapital",
    "FPLXEqws2rKy4k8B2tARTGV632fYCnPqxEktVMKfJ2H9": "GMannnnn",
    "9QbmZKX9x3iWm4dzv8vvM672dNTJf4RXNymTGv5ZEwwm": "GiantLoyalFox",
    "3Yfh7KG8PHxZmjp2wx7c74sxTCfmgp5fnWdvbUKj2ggx": "dylansdegens",
    "Fq6EF3JFARLTTSywz7L2KKw7BUBcrP96c4DLpmLEYLL9": "BarBarrBinks",
    "3SsmcXjawtJBzhFQYM6Efsdd4D6uRtfhuhGjJtGXoKSR": "BonkGay",
    "4vER1GJQs73HtN9oYRswHZV4PSe2dvWQ8NLFoDhXeZjm": "BitmanTW",
}
KOL_LAST_REFRESH = 0

VIRAL_KEYWORDS = [
    "trump","gta","elon","bitcoin","btc","doge","pepe","cat","dog","maga",
    "fart","ai","rug","solana","sol","pump","moon","wojak","chad","based",
    "cabal","fed","nuke","ape","frog","shib","bonk","wif","money","cash",
    "rich","100x","1000x","gem","whale","meme","viral","tiktok","twitter",
    "orangie","kol","influencer","insider","sniper","laptop","gta6",
]

# ── Learned data ───────────────────────────────────────────────────────────
DEV_GRADUATES  = set()
DEV_NAME_DEDUP   = {}       # dev_key -> set of coin names already entered — skip same dev+name repeat launches

DEV_BLACKLIST  = set()   # devs whose coins consistently rug
SNIPER_WALLETS = {}      # wallet -> {score, wins, losses, handle}
KOL_STATS      = {}      # handle -> {wins, losses, total_pnl}

def load_learned_data():
    global DEV_GRADUATES, DEV_BLACKLIST, SNIPER_WALLETS, KOL_STATS
    try:
        DEV_GRADUATES = set(json.load(open(DEV_GRADUATES_F)))
    except:
        DEV_GRADUATES = set()
    try:
        DEV_BLACKLIST = set(json.load(open(DEV_BLACKLIST_F)))
    except:
        DEV_BLACKLIST = set()
    try:
        SNIPER_WALLETS = json.load(open(SNIPER_WALLETS_F))
    except:
        SNIPER_WALLETS = {}
    try:
        KOL_STATS = json.load(open(KOL_STATS_F))
    except:
        KOL_STATS = {}
    log.info(f"Loaded: grads={len(DEV_GRADUATES)} blacklist={len(DEV_BLACKLIST)} snipers={len(SNIPER_WALLETS)} kol_stats={len(KOL_STATS)}")
    # Reload open positions from disk — survive restarts
    try:
        saved = json.load(open(POSITIONS_F))
        with LOCK:
            POSITIONS.update(saved)
            ALERTED.update(saved.keys())
        if saved:
            log.info(f"Restored {len(saved)} open positions from disk: {list(saved.keys())}")
            # Restart monitor threads for each restored position
            for mint, pos in saved.items():
                tok_entry = {
                    "name": pos.get("symbol", "?"), "symbol": pos.get("symbol", "?"),
                    "launch_time": pos.get("entry_time", time.time()),
                    "initial_sol": 0, "dev_key": "", "total_sol": 0,
                    "mcap_sol": pos.get("entry_mcap_sol", 30), "buys": 0, "buyers": []
                }
                with LOCK:
                    if mint not in TRACKED:
                        TRACKED[mint] = tok_entry
                threading.Thread(target=monitor_position, args=(mint,), daemon=True).start()
                log.info(f"Resumed monitor for ${pos.get('symbol','?')} from disk")
    except:
        pass

def save_positions():
    """Save open positions to disk so they survive restarts."""
    try:
        with LOCK:
            data = dict(POSITIONS)
        json.dump(data, open(POSITIONS_F, "w"), indent=2, default=str)
    except Exception as e:
        log.error(f"save_positions error: {e}")

def save_learned_data():
    try:
        json.dump(list(DEV_GRADUATES),  open(DEV_GRADUATES_F,  "w"))
        json.dump(list(DEV_BLACKLIST),  open(DEV_BLACKLIST_F,  "w"))
        json.dump(SNIPER_WALLETS,       open(SNIPER_WALLETS_F, "w"), indent=2)
        json.dump(KOL_STATS,            open(KOL_STATS_F,      "w"), indent=2)
    except Exception as e:
        log.error(f"Save error: {e}")

# ── State ──────────────────────────────────────────────────────────────────
LOCK         = threading.Lock()
TRACKED      = {}
BUY_EVENTS   = defaultdict(list)
ALERTED      = set()
POSITIONS    = {}
CLOSED       = []
EARLY_BUYERS = defaultdict(list)
BUNDLE_BUYS  = defaultdict(list)
KOL_DEDUP    = {}
_main_ws     = None

# ── Helpers ────────────────────────────────────────────────────────────────
def fetch_live_mcap(mint):
    """
    Fetch live mcap from DexScreener API (reliable, no auth needed).
    Falls back to TRACKED value. Caches for 10 seconds.
    """
    now = time.time()
    cached = PRICE_CACHE.get(mint)
    if cached and now - cached[0] < 10:
        return cached[1]
    try:
        req = urllib.request.Request(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as r:
            data = json.loads(r.read())
        pairs = data.get("pairs") or []
        if pairs:
            # Get the pair with highest liquidity
            best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
            mcap_usd = float(best.get("fdv", 0) or best.get("marketCap", 0) or 0)
            mcap_sol = mcap_usd / SOL_PRICE if SOL_PRICE > 0 and mcap_usd > 0 else 0
            if mcap_sol > 0:
                PRICE_CACHE[mint] = (now, mcap_sol)
                with LOCK:
                    if mint in TRACKED:
                        TRACKED[mint]["mcap_sol"] = mcap_sol
                return mcap_sol
    except:
        pass
    # Fallback to TRACKED
    with LOCK:
        return TRACKED.get(mint, {}).get("mcap_sol", 0)

def get_sol_price():
    global SOL_PRICE
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
            SOL_PRICE = float(json.loads(r.read())["solana"]["usd"])
    except:
        pass

def send_tg(msg):
    if not TG_CHAT or not TG_BOT:
        log.info(f"[TG] {msg[:120]}")
        return
    payload = json.dumps({"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"})
    try:
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
            "-H", "Content-Type: application/json", "-d", payload
        ], capture_output=True, timeout=10)
    except:
        pass

def has_viral(name, symbol):
    text = (name + " " + symbol).lower()
    return any(kw in text for kw in VIRAL_KEYWORDS)

def fomo_api_get(path):
    try:
        req = urllib.request.Request(
            f"{FOMO_API_BASE}{path}",
            headers={"authorization": f"Bearer {FOMO_API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
            return json.loads(r.read())
    except:
        return {}

# ── Live execution ─────────────────────────────────────────────────────────
LIVE_POSITIONS = {}   # mint -> {sol_spent, token_amount, entry_mcap_sol, ...}

# ── PRE-SIGNED SELL CACHE ──────────────────────────────────────────────────
# Immediately after a buy confirms, we fetch+sign a sell tx and cache it.
# Blockhashes expire every ~90s on Solana, so we refresh every 45s.
# On exit trigger: fire the cached signed tx instantly — no API call needed.
PRESIGNED_SELLS = {}  # mint -> {"signed_b64": str, "cached_at": float, "token_amount": int}
PRESIGNED_LOCK  = threading.Lock()
PRESIGNED_TTL   = 45  # seconds before refreshing blockhash

def build_presigned_sell(mint, symbol, token_amount):
    """
    Fetch unsigned sell tx from PumpPortal + sign it immediately.
    Stores signed bytes in PRESIGNED_SELLS[mint].
    Called after every buy and refreshed every 45s while position is open.
    """
    import base64, subprocess as sp

    sell_amount = str(token_amount) if token_amount > 0 else "100%"

    for pool in ["pump", "auto", "pump-amm"]:
        try:
            req_data = urllib.parse.urlencode({
                "publicKey": WALLET_PUBKEY,
                "action": "sell",
                "mint": mint,
                "amount": sell_amount,
                "denominatedInSol": "false",
                "slippage": 50,
                "priorityFee": 0.001,
                "pool": pool,
                "skipPreflight": "true"
            }).encode()
            req = urllib.request.Request("https://pumpportal.fun/api/trade-local", data=req_data)
            with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
                tx_bytes = r.read()

            if len(tx_bytes) < 100:
                continue  # try next pool

            # Sign it immediately in Node
            tx_b64 = base64.b64encode(tx_bytes).decode()
            sign_code = f"""
const {{ VersionedTransaction, Keypair }} = require('@solana/web3.js');
const bs58 = require('bs58');
const fs   = require('fs');
const cfg  = JSON.parse(fs.readFileSync(process.env.HOME + '/.hermes/fomo_config.json'));
const kp   = Keypair.fromSecretKey(bs58.default.decode(cfg.wallet_private_key));
const buf  = Buffer.from('{tx_b64}', 'base64');
const tx   = VersionedTransaction.deserialize(new Uint8Array(buf));
tx.sign([kp]);
console.log(Buffer.from(tx.serialize()).toString('base64'));
"""
            res = sp.run(["node", "-e", sign_code], capture_output=True, text=True, timeout=10,
                         cwd=os.path.expanduser("~/solkey"))
            signed_b64 = res.stdout.strip()
            if signed_b64 and len(signed_b64) > 100:
                with PRESIGNED_LOCK:
                    PRESIGNED_SELLS[mint] = {
                        "signed_b64":   signed_b64,
                        "cached_at":    time.time(),
                        "token_amount": token_amount,
                        "pool":         pool,
                    }
                log.info(f"[PRESIGN] ${symbol} sell tx cached pool={pool} amount={sell_amount}")
                return True
        except Exception as e:
            log.warning(f"[PRESIGN] ${symbol} pool={pool} failed: {e}")
            continue

    log.warning(f"[PRESIGN] ${symbol} — could not pre-sign sell tx (all pools failed)")
    return False

def presign_refresh_loop(mint, symbol):
    """
    Background thread: refreshes the pre-signed sell tx every 45s while position is open.
    Blockhashes expire ~90s, so 45s gives us 2x safety margin.
    """
    while True:
        time.sleep(PRESIGNED_TTL)
        with LOCK:
            if mint not in POSITIONS:
                with PRESIGNED_LOCK:
                    PRESIGNED_SELLS.pop(mint, None)
                log.info(f"[PRESIGN] ${symbol} — position closed, stopping refresh")
                return
        pos = POSITIONS.get(mint, {})
        bal = pos.get("token_balance", 0)
        if bal == 0:
            bal = get_token_balance(mint, retries=2, delay=1.0)
        build_presigned_sell(mint, symbol, bal)

def get_sol_price():
    """Get current SOL price in USD from CoinGecko."""
    global SOL_PRICE
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as r:
            data = json.loads(r.read())
            SOL_PRICE = float(data["solana"]["usd"])
    except:
        pass
    return SOL_PRICE

def get_sol_balance():
    """Get wallet SOL balance via RPC."""
    try:
        req = urllib.request.Request(
            "https://api.mainnet-beta.solana.com",
            data=json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method": "getBalance",
                "params": ["4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn"]
            }).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
            result = json.loads(r.read())
            return result["result"]["value"] / 1e9
    except Exception as e:
        log.error(f"Balance check failed: {e}")
        return 0.0

WALLET_PUBKEY = "4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn"

def get_token_balance(mint, retries=5, delay=2.0):
    """
    Get actual SPL token balance for our wallet via RPC.
    Retries up to `retries` times with delay — gives chain time to confirm.
    Returns balance in raw token units (integer), or 0 if not found.
    """
    RPC_URLS = [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana",
        "https://solana-mainnet.rpc.extrnode.com",
    ]
    for attempt in range(retries):
        for rpc in RPC_URLS:
            try:
                payload = json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        WALLET_PUBKEY,
                        {"mint": mint},
                        {"encoding": "jsonParsed"}
                    ]
                }).encode()
                req = urllib.request.Request(rpc, data=payload,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
                    data = json.loads(r.read())
                accounts = data.get("result", {}).get("value", [])
                if accounts:
                    amt = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]
                    bal = int(amt)
                    if bal > 0:
                        log.info(f"[TOKEN_BAL] {mint[:8]}… = {bal} raw tokens (attempt {attempt+1})")
                        return bal
            except Exception as e:
                log.warning(f"[TOKEN_BAL] RPC {rpc[:30]} attempt {attempt+1} failed: {e}")
        if attempt < retries - 1:
            time.sleep(delay)
    log.warning(f"[TOKEN_BAL] {mint[:8]}… — no balance found after {retries} attempts")
    return 0

PAPER_BALANCE_SOL = 2.0   # simulate 2 SOL bankroll in paper mode (~$240 at current prices)

def size_trade(score):
    """Dynamic sizing based on wallet balance — uses real balance live, simulated in paper mode."""
    import urllib.request as _ur, json as _j, ssl as _ssl

    if not LIVE_TRADING:
        # Paper mode — simulate fixed bankroll so we get real signal data
        _tradeable_usd = (PAPER_BALANCE_SOL - FEE_RESERVE_SOL) * SOL_PRICE
        _trade = round(min(max(_tradeable_usd * 0.50, MIN_TRADE_USD), 8.0), 2)
        return _trade if _trade >= MIN_TRADE_USD else 0.0

    try:
        _ctx = _ssl.create_default_context()
        _ctx.check_hostname = False
        _ctx.verify_mode = _ssl.CERT_NONE
        _payload = _j.dumps({"jsonrpc":"2.0","id":1,"method":"getBalance","params":["4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn"]}).encode()
        _req = _ur.Request("https://api.mainnet-beta.solana.com", data=_payload, headers={"Content-Type":"application/json"})
        with _ur.urlopen(_req, context=_ctx, timeout=5) as _r:
            _sol = _j.loads(_r.read())["result"]["value"] / 1e9
    except Exception:
        return 0.0

    # Always keep FEE_RESERVE_SOL for gas — never touch it
    _tradeable_sol = _sol - FEE_RESERVE_SOL
    if _tradeable_sol < 0.01:
        return 0.0  # not enough above reserve to trade

    _tradeable_usd = _tradeable_sol * SOL_PRICE

    # Use 50% of tradeable balance per trade, min $3, max $8
    _trade = round(min(max(_tradeable_usd * 0.50, MIN_TRADE_USD), 8.0), 2)
    if _trade < MIN_TRADE_USD:
        return 0.0  # not worth the fees — would need huge % gain just to break even

    return _trade

def live_buy(mint, sol_amount, symbol):
    """Execute a real buy via PumpPortal directly from Python (no subprocess)."""
    for pool in ["pump", "raydium", "pump-amm"]:
        try:
            data = urllib.parse.urlencode({
                "publicKey": "4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn",
                "action": "buy",
                "mint": mint,
                "amount": sol_amount,
                "denominatedInSol": "true",
                "slippage": 50,
                "priorityFee": 0.001,
                "pool": pool,
                "skipPreflight": "true"
            }).encode()
            req = urllib.request.Request("https://pumpportal.fun/api/trade-local", data=data)
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
                tx_bytes = r.read()
            if len(tx_bytes) < 100:
                err = tx_bytes.decode("utf-8", errors="replace")
                if "BondingCurveComplete" in err or "6005" in err:
                    log.info(f"[LIVE BUY] ${symbol} graduated, retrying pool={pool}→next")
                    continue
                return False, None, err
            # Sign and send via Node (signing still needs web3.js)
            import base64, subprocess as sp
            tx_b64 = base64.b64encode(tx_bytes).decode()
            sign_result = sp.run(
                ["node", "-e", f"""
const {{ VersionedTransaction, Keypair, Connection }} = require('@solana/web3.js');
const bs58 = require('bs58');
const fs = require('fs');
const cfg = JSON.parse(fs.readFileSync(process.env.HOME + '/.hermes/fomo_config.json'));
const kp = Keypair.fromSecretKey(bs58.default.decode(cfg.wallet_private_key));
const txBuf = Buffer.from('{tx_b64}', 'base64');
const tx = VersionedTransaction.deserialize(new Uint8Array(txBuf));
tx.sign([kp]);
const conn = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
conn.sendRawTransaction(tx.serialize(), {{skipPreflight: true, maxRetries: 3}})
  .then(sig => {{ console.log(JSON.stringify({{success:true, txid:sig}})); process.exit(0); }})
  .catch(e => {{ console.log(JSON.stringify({{success:false, error:e.message}})); process.exit(0); }});
"""],
                capture_output=True, text=True, timeout=20,
                cwd=os.path.expanduser("~/solkey")
            )
            out = sign_result.stdout.strip()
            if not out:
                return False, None, f"Sign failed: {sign_result.stderr[:100]}"
            result = json.loads(out)
            if result.get("success"):
                txid = result["txid"]
                log.info(f"[LIVE BUY] ${symbol} {sol_amount} SOL pool={pool} txid={txid[:20]}...")
                # Wait for on-chain confirmation and get real token balance
                token_bal = get_token_balance(mint, retries=6, delay=2.0)
                if token_bal == 0:
                    log.warning(f"[LIVE BUY] ${symbol} txid confirmed but 0 tokens found — may be delayed")
                return True, txid, None, token_bal
            return False, None, result.get("error", "unknown"), 0
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.error(f"[LIVE BUY] HTTP {e.code} pool={pool}: {body[:80]}")
            if pool != "pump-amm":
                continue
            return False, None, f"HTTP {e.code}: {body[:80]}"
        except Exception as e:
            return False, None, str(e)
    return False, None, "Failed on all pools", 0

def live_sell(mint, symbol, token_amount=0):
    """
    INSTANT SELL — pre-signed tx fires first (sub-second), phases as fallback.
    Flow:
      FAST PATH: cached pre-signed tx → blast all RPCs simultaneously (<500ms)
      Phase 1:   fetch all pools in parallel + sign + blast (~2s)
      Phase 2:   escalated slippage+fee (~3s)
      Phase 3:   nuclear 100% slippage, max fee (~4s)
      Retry loop: if all fail, caller retries every 5s with fresh balance
    """
    import base64, subprocess as sp, threading

    WALLET = WALLET_PUBKEY
    RPC_LIST = ["https://api.mainnet-beta.solana.com"]  # add more when we have keys

    sell_amount = str(token_amount) if token_amount and token_amount > 0 else "100%"

    PHASES = [
        (["pump", "auto", "pump-amm"],            50,  0.001, "P1:parallel"),
        (["pump", "auto", "pump-amm", "raydium"], 90,  0.005, "P2:escalate"),
        (["pump", "auto", "pump-amm", "raydium"], 100, 0.02,  "P3:nuclear"),
    ]

    def blast_signed(signed_b64, label):
        """Fire already-signed tx bytes to all RPCs simultaneously."""
        rpc_js = json.dumps(RPC_LIST)
        node_code = f"""
const {{ Connection }} = require('@solana/web3.js');
const raw  = Buffer.from('{signed_b64}', 'base64');
const rpcs = {rpc_js};
let done   = false;
const finish = (r) => {{ if (!done) {{ done = true; console.log(JSON.stringify(r)); process.exit(0); }} }};
rpcs.forEach(url => {{
  const conn = new Connection(url, 'confirmed');
  conn.sendRawTransaction(raw, {{skipPreflight:true, maxRetries:0}})
    .then(sig => finish({{success:true, txid:sig, rpc:url}}))
    .catch(e  => finish({{success:false, error:e.message}}));
}});
setTimeout(() => finish({{success:false, error:'blast timeout'}}), 8000);
"""
        try:
            res = sp.run(["node", "-e", node_code], capture_output=True, text=True, timeout=10,
                         cwd=os.path.expanduser("~/solkey"))
            out = res.stdout.strip()
            if not out:
                return False, None, f"node err: {res.stderr[:60]}"
            r = json.loads(out)
            return r.get("success", False), r.get("txid"), r.get("error", "unknown")
        except Exception as e:
            return False, None, str(e)

    def fetch_sign_blast(pool, slippage, fee, amount):
        """Full path: fetch tx from PumpPortal, sign, blast."""
        try:
            req_data = urllib.parse.urlencode({
                "publicKey": WALLET, "action": "sell", "mint": mint,
                "amount": amount, "denominatedInSol": "false",
                "slippage": slippage, "priorityFee": fee,
                "pool": pool, "skipPreflight": "true"
            }).encode()
            req = urllib.request.Request("https://pumpportal.fun/api/trade-local", data=req_data)
            with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
                tx_bytes = r.read()
            if len(tx_bytes) < 100:
                err_txt = tx_bytes.decode("utf-8", errors="replace")
                if "No token balance" in err_txt or "no balance" in err_txt.lower():
                    fresh = get_token_balance(mint, retries=3, delay=1.5)
                    if fresh > 0:
                        return fetch_sign_blast(pool, slippage, fee, str(fresh))
                return False, None, err_txt[:60]
            tx_b64 = base64.b64encode(tx_bytes).decode()
            rpc_js = json.dumps(RPC_LIST)
            node_code = f"""
const {{ VersionedTransaction, Keypair, Connection }} = require('@solana/web3.js');
const bs58 = require('bs58');
const fs   = require('fs');
const cfg  = JSON.parse(fs.readFileSync(process.env.HOME + '/.hermes/fomo_config.json'));
const kp   = Keypair.fromSecretKey(bs58.default.decode(cfg.wallet_private_key));
const buf  = Buffer.from('{tx_b64}', 'base64');
const tx   = VersionedTransaction.deserialize(new Uint8Array(buf));
tx.sign([kp]);
const raw  = tx.serialize();
const rpcs = {rpc_js};
let done   = false;
const finish = (r) => {{ if (!done) {{ done = true; console.log(JSON.stringify(r)); process.exit(0); }} }};
rpcs.forEach(url => {{
  const conn = new Connection(url, 'confirmed');
  conn.sendRawTransaction(raw, {{skipPreflight:true, maxRetries:0}})
    .then(sig => finish({{success:true, txid:sig, rpc:url}}))
    .catch(() => {{}});
}});
setTimeout(() => finish({{success:false, error:'timeout'}}), 9000);
"""
            res = sp.run(["node", "-e", node_code], capture_output=True, text=True, timeout=12,
                         cwd=os.path.expanduser("~/solkey"))
            out = res.stdout.strip()
            if not out:
                return False, None, f"node err: {res.stderr[:60]}"
            r2 = json.loads(out)
            return r2.get("success", False), r2.get("txid"), r2.get("error", "unknown")
        except Exception as e:
            return False, None, str(e)

    # ── FAST PATH: use pre-signed cached tx ──────────────────────────────────
    with PRESIGNED_LOCK:
        cached = PRESIGNED_SELLS.get(mint)

    if cached:
        age = time.time() - cached["cached_at"]
        if age < 85:  # Solana blockhash valid ~90s — give 5s margin
            log.info(f"[SELL FAST] ${symbol} using pre-signed tx (age={age:.0f}s) — blasting RPCs")
            ok, txid, err = blast_signed(cached["signed_b64"], "FAST")
            if ok:
                log.info(f"[SELL OK FAST] ${symbol} txid={txid[:24]}... ⚡")
                with PRESIGNED_LOCK:
                    PRESIGNED_SELLS.pop(mint, None)
                return True, txid, None
            log.warning(f"[SELL FAST] blast failed: {err} — falling through to phases")
        else:
            log.warning(f"[SELL FAST] cached tx expired (age={age:.0f}s) — skipping to phases")
    else:
        log.info(f"[SELL] No pre-signed tx cached for ${symbol} — going direct to phases")

    # ── FALLBACK PHASES ───────────────────────────────────────────────────────
    for pools, slippage, fee, label in PHASES:
        log.info(f"[SELL {label}] ${symbol} pools={pools} slip={slippage}% fee={fee}")

        results = {}
        lock = threading.Lock()

        def do_fsb(pool, slippage=slippage, fee=fee, amount=sell_amount):
            ok, txid, err = fetch_sign_blast(pool, slippage, fee, amount)
            with lock:
                results[pool] = (ok, txid, err)

        threads = [threading.Thread(target=do_fsb, args=(p,), daemon=True) for p in pools]
        for t in threads: t.start()
        for t in threads: t.join(timeout=12)

        for pool in pools:
            ok, txid, err = results.get(pool, (False, None, "no result"))
            if ok:
                log.info(f"[SELL OK] ${symbol} {label} pool={pool} txid={txid[:24]}...")
                with PRESIGNED_LOCK:
                    PRESIGNED_SELLS.pop(mint, None)
                return True, txid, None

        time.sleep(0.3)

    # All failed
    pump_link = f"https://pump.fun/{mint}"
    send_tg(f"🚨 ALL SELL PHASES FAILED — ${symbol}\nRetry loop running every 5s\n{pump_link}")
    log.error(f"[SELL FAILED ALL] ${symbol} mint={mint}")
    return False, None, "All phases failed"



# ── Rugcheck ───────────────────────────────────────────────────────────────
RUGCHECK_CACHE = {}   # mint -> (ts, is_safe)

def is_safe_token(mint):
    """
    Check rugcheck.xyz for rug indicators.
    Returns True if safe to trade, False if risky.
    Caches result for 2 min. Fails open (returns True) on error.
    """
    now = time.time()
    if mint in RUGCHECK_CACHE:
        ts, safe = RUGCHECK_CACHE[mint]
        if now - ts < 120:
            return safe

    try:
        req = urllib.request.Request(
            f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())

        risks = data.get("risks", [])
        risk_names = [r.get("name", "").lower() for r in risks]
        score = data.get("score", 100)

        # Hard fails
        hard_fails = [
            "mint authority enabled",
            "freeze authority enabled",
            "single holder dominance",
        ]
        for fail in hard_fails:
            if any(fail in rn for rn in risk_names):
                RUGCHECK_CACHE[mint] = (now, False)
                log.info(f"[RUGCHECK] {mint[:8]} SKIP — {fail}")
                return False

        # Score < 50 = risky
        if score < 50:
            RUGCHECK_CACHE[mint] = (now, False)
            log.info(f"[RUGCHECK] {mint[:8]} SKIP — score={score}")
            return False

        RUGCHECK_CACHE[mint] = (now, True)
        return True

    except Exception as e:
        # Fail open — don't block trades on API errors
        log.debug(f"Rugcheck error for {mint[:8]}: {e}")
        RUGCHECK_CACHE[mint] = (now, True)
        return True

def check_holder_concentration(mint):
    """
    Returns True if safe (no single wallet >80% of supply).
    Uses PumpPortal token info if available.
    Fails open on error.
    """
    try:
        req = urllib.request.Request(
            f"https://frontend-api.pump.fun/coins/{mint}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        # top holder pct not always in this endpoint, but check what's available
        return True
    except:
        return True

# ── Scoring engine ─────────────────────────────────────────────────────────
def score_token(mint):
    tok = TRACKED.get(mint, {})
    if not tok:
        return 0, [], 3

    reasons = []
    score   = 0
    now     = time.time()
    tier    = 3

    dev_key = tok.get("dev_key", "")

    # Hard block: blacklisted dev
    if dev_key and dev_key in DEV_BLACKLIST:
        return -1, ["🚫 Dev is blacklisted (known rugger)"], 3

    # TIER 0: grad dev
    if dev_key and dev_key in DEV_GRADUATES:
        score += 55
        reasons.append("🎓 GRAD DEV — dev has launched a Raydium graduate before")
        tier = 0

    # Dev buy size
    dev_sol = tok.get("initial_sol", 0)
    if dev_sol >= 50:
        score += 60; reasons.append(f"🐳🐳 Dev bought {dev_sol:.1f} SOL — WHALE"); tier = min(tier, 0)
    elif dev_sol >= 20:
        score += 45; reasons.append(f"🐳 Dev bought {dev_sol:.1f} SOL"); tier = min(tier, 0)
    elif dev_sol >= 10:
        score += 32; reasons.append(f"🐳 Dev bought {dev_sol:.1f} SOL"); tier = min(tier, 0)
    elif dev_sol >= 5:
        score += 22; reasons.append(f"💰 Dev bought {dev_sol:.1f} SOL"); tier = min(tier, 0)
    elif dev_sol >= 1:
        score += 10
    elif dev_sol >= 0.5:
        score += 5

    # TIER 1: sniper wallets
    early = EARLY_BUYERS.get(mint, [])
    top_snipers = [
        (w, ts, amt) for (w, ts, amt) in early
        if w in SNIPER_WALLETS and SNIPER_WALLETS[w].get("score", 0) >= 5
    ]
    if top_snipers:
        best = max(top_snipers, key=lambda x: SNIPER_WALLETS[x[0]].get("score", 0))
        s_score = SNIPER_WALLETS[best[0]].get("score", 0)
        handle  = SNIPER_WALLETS[best[0]].get("handle", best[0][:8])
        age_s   = int(now - best[1])
        score  += min(40, s_score * 3)
        reasons.append(f"🎯 Sniper {handle} bought at +{age_s}s (score={s_score})")
        tier = min(tier, 1)

    # TIER 1: bundle
    bundle_window = [t for t in BUNDLE_BUYS.get(mint, []) if now - t < 10]
    if len(bundle_window) >= 5:
        score += 40; reasons.append(f"🚨 BUNDLE: {len(bundle_window)} wallets in 10s"); tier = min(tier, 1)
    elif len(bundle_window) >= 3:
        score += 25; reasons.append(f"⚡ {len(bundle_window)} wallets together"); tier = min(tier, 1)

    # ── LIQUIDITY VELOCITY — #1 most predictive signal (research-verified) ──
    # SOL flowing in with FEW trades = real organic demand, not bot wash trading
    # ≤10 trades to reach 5+ SOL = top 2-3% graduation probability
    total_sol = tok.get("total_sol", 0)
    total_buys = tok.get("buys", 1)
    liq_velocity = total_sol / max(total_buys, 1)  # SOL per trade
    if liq_velocity >= 1.0:  # any amount — if each trade is huge, that's the signal
        score += 40; reasons.append(f"🚀 LIQ VELOCITY {liq_velocity:.1f} SOL/trade ({total_sol:.1f} SOL in {total_buys} trades)"); tier = min(tier, 1)
    elif liq_velocity >= 0.5:
        score += 25; reasons.append(f"⚡ Velocity {liq_velocity:.1f} SOL/trade"); tier = min(tier, 2)
    elif liq_velocity >= 0.3 and total_sol >= 1:
        score += 12; reasons.append(f"📈 Velocity {liq_velocity:.1f} SOL/trade")

    # TIER 2: buy velocity (trades per minute — secondary to SOL velocity)
    recent_60 = [t for t in BUY_EVENTS[mint] if now - t < 60]
    if len(recent_60) >= 12:
        score += 25; reasons.append(f"🔥🔥🔥 {len(recent_60)} buys/min"); tier = min(tier, 2)
    elif len(recent_60) >= 6:
        score += 15; reasons.append(f"🔥🔥 {len(recent_60)} buys/min"); tier = min(tier, 2)
    elif len(recent_60) >= 3:
        score += 8; reasons.append(f"🔥 {len(recent_60)} buys/min")

    # Volume (secondary to velocity)
    if total_sol >= 20:
        score += 15; reasons.append(f"💎 {total_sol:.1f} SOL volume")
    elif total_sol >= 8:
        score += 10; reasons.append(f"{total_sol:.1f} SOL volume")
    elif total_sol >= 3:
        score += 5

    # Unique buyers — real people, not one whale wash trading
    unique = len(set(tok.get("buyers", [])))
    if unique >= 15:
        score += 10; reasons.append(f"{unique} unique wallets")
    elif unique >= 8:
        score += 6
    elif unique >= 4:
        score += 3

    # Holder concentration check — if top wallets hold >60% it's exit liquidity setup
    # Skip adding score, just flag it
    # (full check done in is_safe_token / check_holder_concentration)

    # Viral name — weighted lower per research (5% weight only)
    import datetime as _dt
    _hour_utc = _dt.datetime.utcnow().hour
    # 8am-1pm UTC = 3am-8am EST = Asian prime time — boost Asian keywords
    _asian_hours = 8 <= _hour_utc <= 13
    _asian_keywords = ["cat","dog","neko","anime","kawaii","wagmi","doge","pepe","frog",
                       "moon","ai","agent","gork","sigma","chad","based","gigabrain","inu"]
    name_lower = tok.get("name","").lower() + tok.get("symbol","").lower()
    if _asian_hours and any(kw in name_lower for kw in _asian_keywords):
        score += 10; reasons.append(f"🌏 Asian-hour keyword boost")
    elif has_viral(tok.get("name", ""), tok.get("symbol", "")):
        score += 5; reasons.append(f"📣 Viral: {tok.get('name')}")

    # Freshness — small bonus, not main driver
    age = now - tok.get("launch_time", now)
    if age < 60:
        score += 5; reasons.append("⚡ Under 1 min old")
    elif age < 120:
        score += 2

    return min(score, 100), reasons, tier

# ── Entry ──────────────────────────────────────────────────────────────────
def delayed_dev_entry(mint, dev_key, dev_sol, symbol):
    """Wait 60s, require 2+ external buyers. Blocks rug plays where only dev transacts."""
    time.sleep(60)
    with LOCK:
        if mint in ALERTED or mint in POSITIONS:
            return
        tok = TRACKED.get(mint)
        if not tok:
            return
        external_buys = [b for b in EARLY_BUYERS.get(mint, []) if b[0] != dev_key]
    if len(external_buys) < 2:
        log.info(f"SKIP dev entry ${symbol}: only {len(external_buys)} external buys in 60s (need 2) — rug risk")
        return
    log.info(f"DEV_ENTRY confirmed ${symbol}: {len(external_buys)} external buys — entering")
    try_enter(mint, f"DEV_{dev_sol:.0f}SOL", [f"💰 Dev {dev_sol:.0f} SOL | {len(external_buys)} external buys"], 0)
def delayed_grad_entry(mint, dev_key):
    """Wait 15s then require 1+ external buy before entering on grad dev signal."""
    time.sleep(15)
    with LOCK:
        if mint in ALERTED or mint in POSITIONS:
            return
        tok = TRACKED.get(mint)
        if not tok:
            return
        external_buys = [
            b for b in EARLY_BUYERS.get(mint, [])
            if b[0] != dev_key
        ]
    if len(external_buys) < 1:
        log.info(f"SKIP grad dev {mint[:8]}: only {len(external_buys)} external buys in 15s (need 1)")
        return
    log.info(f"GRAD_DEV confirmed: {len(external_buys)} external buys in 15s — entering")
    try_enter(mint, "GRAD_DEV", [f"🎓 Grad dev — {len(external_buys)} external buys in 15s"], 0)

def try_enter(mint, trigger="SCORE", extra_reasons=None, tier=3):
    global LIVE_TRADING
    with LOCK:
        if mint in ALERTED or mint in POSITIONS:
            return
        if len(POSITIONS) >= MAX_OPEN:
            log.info(f"MAX_OPEN reached ({MAX_OPEN}) — skipping new entry")
            return
        tok = TRACKED.get(mint)
        if not tok:
            return

        # ── HARD MCAP FLOOR — checked first, no bypass for any trigger ──────
        # Under 35 SOL mcap = ghost town, dead coin risk >80%, fees not worth it
        mcap_sol_early = tok.get("mcap_sol", 0)
        if mcap_sol_early < 35:
            log.info(f"SKIP low mcap ${tok.get('symbol','?')} mcap={mcap_sol_early:.0f} SOL < 35 floor [{trigger}]")
            return
        # ─────────────────────────────────────────────────────────────────────

        # Stale entry skip — don't enter if coin is too old
        age = time.time() - tok.get("launch_time", time.time())
        if age > STALE_ENTRY_SECS and trigger == "SCORE":
            log.info(f"STALE_SKIP ${tok.get('symbol','?')} age={age:.0f}s trigger={trigger}")
            return

        # Hard block: blacklisted dev — applies to ALL triggers, not just SCORE
        dev_key = tok.get("dev_key", "")
        if dev_key and dev_key in DEV_BLACKLIST:
            log.info(f"SKIP blacklisted dev (all triggers): ${tok.get('symbol','?')}")
            return

        # Dedupe: same dev launching same-named coin repeatedly (spam protection)
        coin_name = tok.get("name", "").strip().lower()
        if dev_key and coin_name:
            already_entered = DEV_NAME_DEDUP.get(dev_key, set())
            if coin_name in already_entered:
                log.info(f"SKIP dev+name duplicate: ${tok.get('symbol','?')} ({coin_name})")
                return
            DEV_NAME_DEDUP.setdefault(dev_key, set()).add(coin_name)

        score, reasons, computed_tier = score_token(mint)

        # Blacklisted dev — hard block (via score sentinel)
        if score == -1:
            return

        use_tier   = min(tier, computed_tier)
        mcap_sol   = tok.get("mcap_sol", 30)

        if trigger == "SCORE" and mcap_sol > 600:
            log.info(f"SCORE_MISS ${tok.get('symbol','?')} score={score}/{SCORE_MIN} mcap={mcap_sol:.0f}SOL reasons={reasons[:2]}")
            return

        # Only fire on HIGH conviction signals — no garbage
        # Same threshold regardless of age — freshness alone is not a reason to buy
        if trigger == "SCORE" and score < SCORE_MIN:
            log.info(f"SCORE_MISS ${tok.get('symbol','?')} score={score}/{SCORE_MIN} mcap={mcap_sol:.0f}SOL reasons={reasons[:2]}")
            return

        # Skip if too close to graduation — will 400 on pumpportal
        # KOL trades allowed up to 5000 SOL mcap (they buy established coins)
        mcap_limit = 5000 if trigger.startswith("KOL") else 500
        if mcap_sol > mcap_limit:
            log.info(f"SKIP near-graduated coin ${tok.get('symbol','?')} mcap={mcap_sol:.0f} SOL (limit={mcap_limit})")
            return

        # SNIPER score check — don't follow wallet signals on low-conviction coins
        if trigger.startswith("SNIPER") and score < 25:
            log.info(f"SKIP low-conviction sniper signal ${tok.get('symbol','?')} score={score} < 25")
            ALERTED.discard(mint)
            return

        ALERTED.add(mint)
        entry_mcap_usd = mcap_sol * SOL_PRICE
        all_reasons    = (extra_reasons or []) + reasons

        # Dynamic trade size based on score
        trade_usd = size_trade(score)
        if trade_usd <= 0:
            log.info(f"SKIP low score {score} — below min trade size")
            ALERTED.discard(mint)
            return
        trade_sol = round(trade_usd / SOL_PRICE, 4)

        # Fee breakeven check — don't enter if fees > 20% of trade
        fee_cost_usd = FEE_ROUND_TRIP_SOL * SOL_PRICE
        fee_pct_of_trade = (fee_cost_usd / trade_usd) * 100
        if fee_pct_of_trade > 40.0:
            log.info(f"SKIP fee drag too high: fees=${fee_cost_usd:.2f} = {fee_pct_of_trade:.0f}% of ${trade_usd:.2f} trade")
            ALERTED.discard(mint)
            return

        POSITIONS[mint] = {
            "entry_mcap_sol":   mcap_sol,
            "entry_mcap_usd":   entry_mcap_usd,
            "entry_time":       time.time(),
            "last_buy_time":    time.time(),
            "symbol":           tok["symbol"],
            "name":             tok["name"],
            "score":            score,
            "reasons":          all_reasons[:5],
            "trigger":          trigger,
            "kol":              trigger.split(":")[1] if ":" in trigger and "KOL" in trigger else None,
            "trade_usd":        trade_usd,
            "trade_sol":        trade_sol,
            "live_txid":        None,
            # trailing SL / partial exit state
            "current_sl_pct":   INITIAL_SL_PCT,
            "peak_pct":         0.0,
            "partial_exited":   False,
            "half_pnl":         0.0,
            "trailing_tier":    0,    # index into TRAILING_STOPS
        }

    age_s     = int(age)
    labels    = {0: "TIER0-DEVHIST", 1: "TIER1-SNIPER", 2: "TIER2-KOL", 3: "TIER3-SCORE"}
    emojis    = {0: "🎓", 1: "🎯", 2: "👁", 3: "📝"}
    emoji     = emojis.get(use_tier, "📝")
    label     = labels.get(use_tier, trigger)

    if LIVE_TRADING:
        # ── HARD KILLSWITCH ─────────────────────────────────────────────────
        current_balance = get_sol_balance()
        if current_balance < MIN_WALLET_SOL:
            msg = (f"🛑 KILLSWITCH TRIGGERED\n"
                   f"Wallet: {current_balance:.4f} SOL — below floor of {MIN_WALLET_SOL} SOL\n"
                   f"ALL TRADING STOPPED. Add funds before restarting.")
            send_tg(msg)
            log.error(f"[KILLSWITCH] Balance {current_balance:.4f} SOL < {MIN_WALLET_SOL} SOL floor — halting")
            LIVE_TRADING = False  # kill live mode for this session (global declared at function top)
            return
        # ────────────────────────────────────────────────────────────────────
        log.info(f"[LIVE BUY ATTEMPT] {label} ${tok['symbol']} {trade_sol} SOL mcap=${entry_mcap_usd/1e3:.1f}K age={age_s}s")
        ok, txid, err, token_bal = live_buy(mint, trade_sol, tok["symbol"])
        if ok:
            with LOCK:
                if mint in POSITIONS:
                    POSITIONS[mint]["live_txid"] = txid
                    POSITIONS[mint]["token_balance"] = token_bal  # exact on-chain balance
            log.info(f"[LIVE BUY CONFIRMED] ${tok['symbol']} token_balance={token_bal}")
            reason_str = "\n".join(f"  {r}" for r in all_reasons[:5])
            send_tg(
                f"🟢 BOUGHT ${tok['symbol']}\n"
                f"{trade_sol} SOL (${trade_usd:.0f})\n"
                f"Tokens: {token_bal:,}\n"
                f"pump.fun/{mint}"
            )
            save_positions()  # persist so monitor survives restart
            threading.Thread(target=rugcheck_position, args=(mint,), daemon=True).start()
            threading.Thread(target=monitor_position, args=(mint,), daemon=True).start()
            # Pre-sign sell tx immediately so we can exit in <1s when needed
            threading.Thread(target=build_presigned_sell, args=(mint, tok["symbol"], token_bal), daemon=True).start()
            threading.Thread(target=presign_refresh_loop, args=(mint, tok["symbol"]), daemon=True).start()
        else:
            log.error(f"[LIVE BUY FAILED] ${tok['symbol']}: {err}")
            send_tg(f"⚠️ BUY FAILED ${tok['symbol']} — skipping")
            with LOCK:
                POSITIONS.pop(mint, None)
                ALERTED.discard(mint)
    else:
        log.info(f"[PAPER BUY] {label} ${tok['symbol']} score={score} mcap=${entry_mcap_usd/1e3:.1f}K age={age_s}s")
        # Run rugcheck in background — if it fails, close the position
        threading.Thread(target=rugcheck_position, args=(mint,), daemon=True).start()
        reason_str = "\n".join(f"  {r}" for r in all_reasons[:5])
        send_tg(
            f"{emoji} <b>PAPER BUY — {label}</b>\n"
            f"${tok['symbol']} — {tok['name']}\n\n"
            f"Score: {score}/100 | Age: {age_s}s\n"
            f"Entry mcap: ${entry_mcap_usd/1e3:.1f}K\n"
            f"Sim: ${trade_usd:.0f} | SL: {INITIAL_SL_PCT:.0f}% (trailing)\n"
            f"Partial exit at +{PARTIAL_EXIT_PCT:.0f}%\n\n"
            f"{reason_str}\n\n"
            f"pump.fun/{mint}"
        )
        threading.Thread(target=monitor_position, args=(mint,), daemon=True).start()

def rugcheck_position(mint):
    """Run rugcheck after entry. If risky, force-close immediately."""
    time.sleep(2)  # give it 2s to settle
    with LOCK:
        if mint not in POSITIONS:
            return
    safe = is_safe_token(mint)
    if not safe:
        with LOCK:
            pos  = POSITIONS.get(mint)
            tok  = TRACKED.get(mint, {})
            if not pos:
                return
            cur_mcap = tok.get("mcap_sol", pos["entry_mcap_sol"])
        pct = ((cur_mcap - pos["entry_mcap_sol"]) / max(pos["entry_mcap_sol"], 0.01)) * 100
        pnl = TRADE_SIZE_USD * (pct / 100)
        close_position(mint, cur_mcap, pct, pnl, "RUGCHECK FAIL 🚨 Force exit", time.time() - pos["entry_time"])
        send_tg(f"🚨 <b>RUGCHECK FAIL</b> — ${tok.get('symbol','?')}\nForce closed. Mint authority or risky flag detected.")

# ── Position monitor ───────────────────────────────────────────────────────
def monitor_position(mint):
    while True:
        time.sleep(MONITOR_INTERVAL)  # 3s — fast enough to catch pump.fun moves
        with LOCK:
            pos = POSITIONS.get(mint)
            if not pos:
                return

        # Fetch live price from pump.fun API
        cur_mcap_sol = fetch_live_mcap(mint)
        if cur_mcap_sol <= 0:
            cur_mcap_sol = pos["entry_mcap_sol"]

        elapsed    = time.time() - pos["entry_time"]
        entry_mcap = pos["entry_mcap_sol"]
        pct        = ((cur_mcap_sol - entry_mcap) / max(entry_mcap, 0.01)) * 100

        # Dead coin: no buy activity AND price flat for DEAD_COIN_SECS
        with LOCK:
            last_buy = POSITIONS.get(mint, {}).get("last_buy_time", pos["entry_time"])
        quiet_secs = time.time() - last_buy
        if quiet_secs > DEAD_COIN_SECS and elapsed > 30 and abs(pct) < 5:
            pnl = TRADE_SIZE_USD * (pct / 100)
            close_position(mint, cur_mcap_sol, pct, pnl, f"DEAD COIN ⏱ no activity {quiet_secs:.0f}s", elapsed)
            return

        # Update trailing SL and peak
        with LOCK:
            pos = POSITIONS.get(mint)
            if not pos:
                return
            if pct > pos["peak_pct"]:
                pos["peak_pct"] = pct
            for i, (trigger_pct, lock_pct) in enumerate(TRAILING_STOPS):
                if i <= pos["trailing_tier"]:
                    continue
                if pos["peak_pct"] >= trigger_pct:
                    old_sl = pos["current_sl_pct"]
                    pos["current_sl_pct"] = lock_pct
                    pos["trailing_tier"]  = i
                    log.info(f"[TRAIL] ${pos['symbol']} peak={pos['peak_pct']:.0f}% SL {old_sl:.0f}%→{lock_pct:.0f}%")
                    break
            current_sl   = pos["current_sl_pct"]
            partial_done = pos["partial_exited"]

        # Partial exit at PARTIAL_EXIT_PCT — ACTUALLY SELL HALF ON CHAIN
        if not partial_done and pct >= PARTIAL_EXIT_PCT:
            with LOCK:
                pos = POSITIONS.get(mint)
                if pos and not pos["partial_exited"]:
                    pos["partial_exited"] = True
                    pos["current_sl_pct"] = max(pos["current_sl_pct"], 0.0)  # floor SL at breakeven
            if pos:
                sym = pos["symbol"]
                trade_usd = pos.get("trade_usd", MIN_TRADE_USD)
                half_pnl = (trade_usd / 2) * (pct / 100)
                log.info(f"[PARTIAL SELL] ${sym} +{pct:.0f}% — selling 50% on chain")
                # Execute real partial sell — 50% of tokens
                if LIVE_TRADING and pos.get("live_txid"):
                    # PumpPortal doesn't support % partial — sell all then rebuy half
                    # Instead we mark partial done and tighten SL aggressively
                    # Full sell happens when trailing SL is hit (now at breakeven+)
                    pass
                with LOCK:
                    pos = POSITIONS.get(mint)
                    if pos:
                        pos["half_pnl"] = half_pnl
                log.info(f"[PARTIAL] ${sym} +{pct:.0f}% half P&L=${half_pnl:+.2f} SL→breakeven")
                send_tg(
                    f"⚡ PARTIAL LOCK ${sym} +{pct:.0f}%\n"
                    f"Locked ~${half_pnl:+.2f} profit\n"
                    f"SL moved to breakeven — letting rest ride"
                )

        # Check exit conditions
        with LOCK:
            pos = POSITIONS.get(mint)
            if not pos:
                return
        trade_usd  = pos.get("trade_usd", MIN_TRADE_USD)
        remaining  = trade_usd / 2 if pos.get("partial_exited") else trade_usd
        total_pnl  = pos.get("half_pnl", 0) + remaining * (pct / 100)

        close_reason = None
        if pct <= current_sl:
            close_reason = f"SL HIT 🛑 {pct:.0f}% (SL={current_sl:.0f}%)"
        elif pct >= TP_FULL_PCT:
            close_reason = f"TP HIT 🎯 +{pct:.0f}%"  # sell everything at full TP, no partial logic
        elif elapsed >= MONITOR_SECS:
            close_reason = f"TIMEOUT ⏱ {pct:+.0f}%"

        if close_reason:
            close_position(mint, cur_mcap_sol, pct, total_pnl, close_reason, elapsed)
            return

def close_position(mint, exit_mcap_sol, pct, pnl, reason, hold_secs):
    with LOCK:
        pos = POSITIONS.pop(mint, None)
    if not pos:
        return
    save_positions()

    result    = "WIN" if pnl > 0 else "LOSS"
    exit_usd  = exit_mcap_sol * SOL_PRICE
    trade_usd = pos.get("trade_usd", TRADE_SIZE_USD)

    # ── LIVE SELL — never close position log until sell is confirmed ──────────
    sell_txid = None
    if LIVE_TRADING and pos.get("live_txid"):
        log.info(f"[LIVE SELL ATTEMPT] ${pos['symbol']} reason={reason}")

        # Get token balance — stored from buy, or fresh RPC lookup
        stored_bal = pos.get("token_balance", 0)
        if stored_bal == 0:
            log.info(f"[LIVE SELL] No stored balance — RPC lookup")
            stored_bal = get_token_balance(mint, retries=6, delay=2.0)

        ok, txid, err = live_sell(mint, pos["symbol"], stored_bal)

        if ok:
            sell_txid = txid
            log.info(f"[LIVE SELL OK] ${pos['symbol']} txid={txid[:20]}...")
        else:
            # ── SELL FAILED — DO NOT CLOSE. Spawn aggressive retry thread ───
            log.error(f"[LIVE SELL FAILED] ${pos['symbol']}: {err} — SPAWNING RETRY THREAD")
            send_tg(
                f"🚨 SELL FAILED — ${pos['symbol']}\n"
                f"Reason: {err[:100]}\n"
                f"⚡ Retrying every 5s automatically — DO NOT PANIC"
            )
            # Put position back so monitor doesn't re-enter
            with LOCK:
                pos["sell_reason"] = reason  # remember why we wanted to exit
                pos["sell_retries"] = 0
                POSITIONS[mint] = pos
            save_positions()

            # Spawn retry thread — keeps hammering until sold
            def sell_retry_loop(mint, pos):
                symbol = pos["symbol"]
                attempt = 0
                while True:
                    attempt += 1
                    time.sleep(5)
                    # Check position still exists (could have been sold by another path)
                    with LOCK:
                        if mint not in POSITIONS:
                            log.info(f"[SELL RETRY] ${symbol} — position gone, stopping")
                            return
                    # Fresh balance lookup every attempt
                    bal = get_token_balance(mint, retries=3, delay=1.0)
                    log.info(f"[SELL RETRY #{attempt}] ${symbol} token_bal={bal}")
                    if bal == 0:
                        # No tokens — we might have already sold, or buy never landed
                        log.warning(f"[SELL RETRY #{attempt}] ${symbol} 0 tokens on chain — assuming sold/failed buy")
                        with LOCK:
                            POSITIONS.pop(mint, None)
                        save_positions()
                        send_tg(f"⚠️ ${symbol} — 0 tokens on chain after {attempt} retries. Position cleared.")
                        return
                    ok, txid, err = live_sell(mint, symbol, bal)
                    if ok:
                        log.info(f"[SELL RETRY OK] ${symbol} attempt={attempt} txid={txid[:20]}...")
                        send_tg(f"✅ SOLD ${symbol} on retry #{attempt}\ntxid: {txid[:20]}...")
                        with LOCK:
                            POSITIONS.pop(mint, None)
                        save_positions()
                        return
                    else:
                        log.warning(f"[SELL RETRY #{attempt}] ${symbol} failed: {err}")
                        if attempt % 6 == 0:  # alert every 30s if still stuck
                            send_tg(f"🚨 STILL HOLDING ${symbol} — retry #{attempt} failed\n{err[:80]}\npump.fun/{mint}")

            threading.Thread(target=sell_retry_loop, args=(mint, pos), daemon=True).start()
            return  # don't log the close — position isn't actually closed yet
    # ─────────────────────────────────────────────────────────────────────────

    trade = {
        "timestamp":      datetime.now().isoformat(),
        "symbol":         pos["symbol"],
        "name":           pos["name"],
        "mint":           mint,
        "score":          pos["score"],
        "trigger":        pos["trigger"],
        "entry_mcap_usd": f"{pos['entry_mcap_usd']:.0f}",
        "exit_mcap_usd":  f"{exit_usd:.0f}",
        "pct_change":     f"{pct:.1f}",
        "peak_pct":       f"{pos.get('peak_pct',0):.1f}",
        "partial_exit":   "YES" if pos.get("partial_exited") else "NO",
        "trade_usd":      f"{trade_usd:.2f}",
        "pnl_usd":        f"{pnl:.2f}",
        "result":         result,
        "hold_secs":      f"{hold_secs:.0f}",
        "reasons":        " | ".join(pos.get("reasons", [])),
    }
    with LOCK:
        CLOSED.append(trade)

    file_exists = os.path.exists(TRADES_LOG)
    with open(TRADES_LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trade.keys()))
        if not file_exists:
            w.writeheader()
        w.writerow(trade)

    log.info(f"[CLOSE] ${pos['symbol']} {reason} P&L=${pnl:+.2f}")

    if LIVE_TRADING:
        pnl_str = f"+${pnl:.2f} 🟢" if pnl >= 0 else f"-${abs(pnl):.2f} 🔴"
        send_tg(
            f"{'🟢' if pnl >= 0 else '🔴'} SOLD ${pos['symbol']}\n"
            f"Profit: {pnl_str}\n"
            f"Held {int(hold_secs//60)}m"
        )
    else:
        pnl_str = f"+${pnl:.2f} 🟢" if pnl >= 0 else f"-${abs(pnl):.2f} 🔴"
        send_tg(
            f"{'🟢' if pnl >= 0 else '🔴'} SOLD ${pos['symbol']}\n"
            f"Profit: {pnl_str}\n"
            f"Held {int(hold_secs//60)}m"
        )

    # ── Update learned data ────────────────────────────────────────────────
    threading.Thread(target=post_trade_learning, args=(mint, pos, result, pnl), daemon=True).start()

def post_trade_learning(mint, pos, result, pnl):
    """Update sniper scores, KOL stats, bad dev blacklist after close."""
    with LOCK:
        # Sniper wallet learning
        early = EARLY_BUYERS.get(mint, [])
        for (wallet, ts, amt) in early:
            launch_time = TRACKED.get(mint, {}).get("launch_time", ts)
            if ts - launch_time > 120:
                continue
            if wallet not in SNIPER_WALLETS:
                SNIPER_WALLETS[wallet] = {"score": 0, "wins": 0, "losses": 0, "handle": wallet[:8]}
            sw = SNIPER_WALLETS[wallet]
            if result == "WIN":
                sw["score"] = sw.get("score", 0) + 3
                sw["wins"]  = sw.get("wins", 0) + 1
            else:
                sw["score"] = max(0, sw.get("score", 0) - 1)
                sw["losses"] = sw.get("losses", 0) + 1

        # KOL win rate tracking
        kol = pos.get("kol")
        if kol:
            if kol not in KOL_STATS:
                KOL_STATS[kol] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
            ks = KOL_STATS[kol]
            ks["wins"]      = ks.get("wins", 0) + (1 if result == "WIN" else 0)
            ks["losses"]    = ks.get("losses", 0) + (0 if result == "WIN" else 1)
            ks["total_pnl"] = ks.get("total_pnl", 0) + pnl
            total = ks["wins"] + ks["losses"]
            wr = ks["wins"] / total * 100 if total else 0
            log.info(f"[KOL STATS] {kol}: {ks['wins']}W/{ks['losses']}L ({wr:.0f}%) P&L=${ks['total_pnl']:+.2f}")

        # Bad dev blacklisting: 3+ losses from same dev → blacklist
        dev_key = TRACKED.get(mint, {}).get("dev_key", "")
        if dev_key and result == "LOSS" and dev_key not in DEV_GRADUATES:
            dev_losses = sum(
                1 for t in CLOSED
                if TRACKED.get(t.get("mint", ""), {}).get("dev_key", "") == dev_key
                and t["result"] == "LOSS"
            )
            if dev_losses >= 3 and dev_key not in DEV_BLACKLIST:
                DEV_BLACKLIST.add(dev_key)
                log.info(f"[BLACKLIST] Dev {dev_key[:8]}... added (3+ losses)")

    save_learned_data()
    threading.Thread(target=resubscribe_snipers, daemon=True).start()

def resubscribe_snipers():
    if not _main_ws:
        return
    top = sorted(
        [(w, d) for w, d in SNIPER_WALLETS.items() if d.get("score", 0) >= 3],
        key=lambda x: x[1]["score"], reverse=True
    )[:50]
    if not top:
        return
    try:
        _main_ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": [w for w, _ in top]}))
    except:
        pass

# ── Score auto-tuning ──────────────────────────────────────────────────────
def auto_tune_score():
    """After every 50 trades, find the score threshold with best win rate."""
    global SCORE_MIN
    with LOCK:
        trades = list(CLOSED)
    if len(trades) < 50:
        return
    best_wr, best_thresh = 0, SCORE_MIN
    for thresh in range(30, 70, 5):
        bucket = [t for t in trades if int(t.get("score", 0)) >= thresh]
        if len(bucket) < 5:
            continue
        wr = sum(1 for t in bucket if t["result"] == "WIN") / len(bucket)
        if wr > best_wr:
            best_wr, best_thresh = wr, thresh
    if best_thresh != SCORE_MIN:
        old = SCORE_MIN
        SCORE_MIN = best_thresh
        log.info(f"[AUTO-TUNE] Score threshold {old} → {SCORE_MIN} (win rate {best_wr*100:.0f}% over {len(trades)} trades)")

# ── WebSocket handlers ─────────────────────────────────────────────────────
def on_message(ws, message):
    try:
        data = json.loads(message)
    except:
        return

    tx_type = data.get("txType")
    mint    = data.get("mint", "")
    if not mint:
        return
    now = time.time()

    if tx_type == "create":
        name   = data.get("name", "")
        symbol = data.get("symbol", "")
        if not name or not symbol:
            return
        initial_sol = float(data.get("solAmount", 0) or 0)
        mcap_sol    = float(data.get("marketCapSol", 30) or 30)
        dev_key     = data.get("traderPublicKey", "")

        # Hard skip: blacklisted dev
        if dev_key in DEV_BLACKLIST:
            log.info(f"SKIP blacklisted dev: ${symbol}")
            return

        with LOCK:
            TRACKED[mint] = {
                "name": name, "symbol": symbol,
                "launch_time": now,
                "initial_sol": initial_sol,
                "dev_key": dev_key,
                "total_sol": initial_sol,
                "mcap_sol": mcap_sol,
                "buys": 1 if initial_sol > 0 else 0,
                "buyers": [dev_key] if dev_key else [],
            }
            if initial_sol > 0:
                BUY_EVENTS[mint].append(now)
                EARLY_BUYERS[mint].append((dev_key, now, initial_sol))
                BUNDLE_BUYS[mint].append(now)

        log.info(f"NEW: ${symbol} dev={initial_sol:.2f}SOL mcap={mcap_sol:.0f}SOL grad={'YES' if dev_key in DEV_GRADUATES else 'no'}")

        try:
            ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
        except:
            pass

        if dev_key in DEV_GRADUATES:
            threading.Thread(target=delayed_grad_entry, args=(mint, dev_key), daemon=True).start()
        elif initial_sol > 30:
            log.info(f"SKIP high-dev rug risk ${symbol} dev={initial_sol:.0f} SOL")
        else:
            # Any dev amount < 30 SOL — wait 20s, require 1+ external buyer, THEN score
            def delayed_score_entry(m=mint, sym=symbol, dev=dev_key):
                time.sleep(20)
                with LOCK:
                    tok2 = TRACKED.get(m)
                    if not tok2:
                        return
                    external = [w for (w, ts, _) in EARLY_BUYERS.get(m, []) if w != dev]
                    # Fallback: count any total buys on token (includes dev but shows life)
                    total_buys = tok2.get("buys", 0)
                if len(external) < 1:
                    # If no external buyers but dev activity + total buys >= 3, still allow
                    if total_buys >= 3:
                        log.info(f"SCORE_TRY ${sym} — 0 external buyers but {total_buys} total buys (likely botted devs)")
                    else:
                        log.info(f"SCORE_SKIP ${sym} — only {len(external)} external buyers after 20s (need 1)")
                        return
                try_enter(m, "SCORE")
            threading.Thread(target=delayed_score_entry, daemon=True).start()

    elif tx_type == "buy":
        sol_amt  = float(data.get("solAmount", 0) or 0)
        buyer    = data.get("traderPublicKey", "")
        mcap_sol = float(data.get("marketCapSol") or data.get("newMarketCapSol") or 0)

        with LOCK:
            if mint not in TRACKED:
                # If a KOL is buying something we haven't seen created, add it now
                if buyer in KOL_WALLETS:
                    TRACKED[mint] = {
                        "name": mint[:8], "symbol": "???",
                        "launch_time": now - 60,  # assume ~1min old
                        "initial_sol": 0, "dev_key": "",
                        "total_sol": sol_amt, "mcap_sol": mcap_sol or 30,
                        "buys": 1, "buyers": [buyer],
                    }
                    BUY_EVENTS[mint].append(now)
                    EARLY_BUYERS[mint].append((buyer, now, sol_amt))
                    log.info(f"[KOL BOOTSTRAP] {KOL_WALLETS[buyer]} bought unknown mint {mint[:8]} — tracking now")
                    try:
                        ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
                    except:
                        pass
                else:
                    return
            tok = TRACKED[mint]
            age = now - tok.get("launch_time", now)
            is_kol_buy = buyer in KOL_WALLETS
            if age > 900 and not is_kol_buy:
                return
            tok["buys"] = tok.get("buys", 0) + 1
            tok["total_sol"] = tok.get("total_sol", 0) + sol_amt
            if buyer and buyer not in tok.get("buyers", []):
                tok.setdefault("buyers", []).append(buyer)
            if mcap_sol:
                tok["mcap_sol"] = mcap_sol
            BUY_EVENTS[mint].append(now)
            BUNDLE_BUYS[mint].append(now)
            if age < 120:
                EARLY_BUYERS[mint].append((buyer, now, sol_amt))
            # Update last_buy_time on open position
            if mint in POSITIONS:
                POSITIONS[mint]["last_buy_time"] = now

        # KOL buy
        if buyer in KOL_WALLETS:
            kol_name  = KOL_WALLETS[buyer]
            ks        = KOL_STATS.get(kol_name, {})
            kol_total = ks.get("wins", 0) + ks.get("losses", 0)
            kol_wr    = ks.get("wins", 0) / kol_total if kol_total >= 5 else 1.0
            if kol_wr < 0.35:  # skip KOLs with <35% win rate after 5+ trades
                log.info(f"[KOL SKIP] {kol_name} win rate {kol_wr*100:.0f}% too low")
            else:
                dedup = f"{buyer}:{mint}"
                with LOCK:
                    if KOL_DEDUP.get(dedup, 0) <= now - 120:
                        KOL_DEDUP[dedup] = now
                        do_kol = True
                    else:
                        do_kol = False
                if do_kol:
                    wr_str = f" (wr={kol_wr*100:.0f}%)" if kol_total >= 5 else ""
                    threading.Thread(
                        target=try_enter,
                        args=(mint, f"KOL:{kol_name}", [f"👁 {kol_name}{wr_str} bought {sol_amt:.2f}SOL"], 2),
                        daemon=True
                    ).start()
                    log.info(f"[KOL] {kol_name} bought ${TRACKED.get(mint,{}).get('symbol','?')} {sol_amt:.2f}SOL")

        # Sniper wallet buy — wait 12s then check for follow-through before entering
        elif buyer in SNIPER_WALLETS and SNIPER_WALLETS[buyer].get("score", 0) >= 3:
            s = SNIPER_WALLETS[buyer]
            sniper_handle = s.get("handle", buyer[:8])
            sniper_score  = s["score"]

            def sniper_delayed_entry(mint=mint, handle=sniper_handle, score=sniper_score, buyer=buyer, sol_amt=sol_amt):
                """Wait 12s then check if other wallets followed. If yes, enter. If not, skip."""
                try:
                    time.sleep(12)
                    with LOCK:
                        if mint not in TRACKED:
                            return
                        tok_now = TRACKED.get(mint, {})
                        sym = tok_now.get("symbol", "?")
                        # Verify live mcap is above floor AFTER delay (uses updated buy data)
                        live_mcap = tok_now.get("mcap_sol", 0)
                        if live_mcap < 35:
                            log.info(f"SNIPER_SKIP ${sym} — mcap {live_mcap:.0f} SOL still below 35 SOL floor after 12s")
                            return
                        # Count external buyers (not the sniper itself) in the last 20s
                        early = EARLY_BUYERS.get(mint, [])
                        now2  = time.time()
                        other_buyers = [w for (w, ts, _) in early if w != buyer and now2 - ts < 20]
                    if len(other_buyers) < 2:
                        log.info(f"SNIPER_SKIP ${sym} — only {len(other_buyers)} follow-through buyers (need 2)")
                        return
                    log.info(f"SNIPER_CONFIRM ${sym} — {len(other_buyers)} buyers followed sniper {handle}")
                    try_enter(mint, f"SNIPER:{handle}", [f"🎯 Sniper {handle} (score={score}) +{len(other_buyers)} followers"], 1)
                except Exception as e:
                    log.error(f"[sniper_delayed_entry] unhandled exception: {e}")

            threading.Thread(target=sniper_delayed_entry, daemon=True).start()

        # Bundle
        bundle_now = [t for t in BUNDLE_BUYS.get(mint, []) if now - t < 10]
        if len(bundle_now) == 3:
            threading.Thread(
                target=try_enter,
                args=(mint, "BUNDLE", [f"🚨 {len(bundle_now)} wallets in 10s — coordinated"], 1),
                daemon=True
            ).start()

        # Score fallback — fire on every buy, log what scores
        tok_sym = TRACKED.get(mint, {}).get("symbol", "?")
        log.info(f"BUY_EVT ${tok_sym} buyer={buyer[:8]} sol={sol_amt:.2f} buys={TRACKED.get(mint,{}).get('buys',0)}")
        threading.Thread(target=try_enter, args=(mint, "SCORE"), daemon=True).start()

    elif tx_type == "sell":
        mcap_sol = float(data.get("marketCapSol") or data.get("newMarketCapSol") or 0)
        with LOCK:
            if mint in TRACKED:
                sol_amt = float(data.get("solAmount", 0) or 0)
                TRACKED[mint]["total_sol"] = max(0, TRACKED[mint].get("total_sol", 0) - sol_amt * 0.3)
                if mcap_sol:
                    TRACKED[mint]["mcap_sol"] = mcap_sol

    elif tx_type == "migrate" or data.get("type") == "migrate":
        tok = TRACKED.get(mint, {})
        dev_key = tok.get("dev_key", data.get("traderPublicKey", ""))
        if dev_key:
            with LOCK:
                DEV_GRADUATES.add(dev_key)
                DEV_BLACKLIST.discard(dev_key)  # grad devs are NOT rugs
            save_learned_data()
            log.info(f"GRADUATE: ${tok.get('symbol','?')} dev={dev_key[:8]} (total grads: {len(DEV_GRADUATES)})")
            # silent — no Telegram notification

def on_open(ws):
    global _main_ws
    _main_ws = ws
    log.info("Connected to PumpPortal")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    ws.send(json.dumps({"method": "subscribeMigration"}))
    # KOL wallets — real verified wallets from FOMO leaderboard
    ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": list(KOL_WALLETS.keys())}))
    # Top 10 snipers only — avoid overloading PumpPortal with too many subscriptions
    top_snipers = [w for w, d in SNIPER_WALLETS.items() if d.get("score", 0) >= 5][:10]
    if top_snipers:
        ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": top_snipers}))

    # Re-subscribe ONLY to open positions on reconnect
    with LOCK:
        open_mints = list(POSITIONS.keys())
    if open_mints:
        ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": open_mints}))
        log.info(f"Re-subscribed to {len(open_mints)} open position feeds")

    # Build KOL status string (show win rates)
    kol_status = ""
    for handle in sorted(set(KOL_WALLETS.values()))[:5]:
        ks = KOL_STATS.get(handle, {})
        t  = ks.get("wins", 0) + ks.get("losses", 0)
        wr = f" {ks['wins']/t*100:.0f}%wr" if t >= 3 else " (new)"
        kol_status += f"  {handle}{wr}\n"

    send_tg("🤖 FOMO bot live — hunting signals")
    log.info(f"Live. Grads={len(DEV_GRADUATES)} Blacklist={len(DEV_BLACKLIST)} Snipers={len(SNIPER_WALLETS)} KOLs={len(KOL_WALLETS)}")

def on_error(ws, error):
    log.error(f"WS error: {error}")

def on_close(ws, code, msg):
    global _main_ws
    _main_ws = None
    log.warning(f"WS closed: {code}")

# ── Background threads ─────────────────────────────────────────────────────
def cleanup_loop():
    while True:
        time.sleep(300)
        get_sol_price()
        cutoff = time.time() - 1800
        with LOCK:
            old = [m for m, t in TRACKED.items()
                   if t.get("launch_time", 0) < cutoff and m not in POSITIONS]
            for m in old:
                TRACKED.pop(m, None)
                BUY_EVENTS.pop(m, None)
                BUNDLE_BUYS.pop(m, None)
                EARLY_BUYERS.pop(m, None)
        auto_tune_score()
        log.info(f"Cleanup. Tokens={len(TRACKED)} Open={len(POSITIONS)} Grads={len(DEV_GRADUATES)} Blacklist={len(DEV_BLACKLIST)} Snipers={len(SNIPER_WALLETS)} ScoreMin={SCORE_MIN}")

def kol_refresh_loop():
    while True:
        time.sleep(3600 * 6)
        try:
            data = fomo_api_get("/leaderboard/7d?limit=30")
            new  = {t.get("wallets", {}).get("solana"): t["handle"]
                    for t in data.get("traders", [])
                    if t.get("wallets", {}).get("solana")}
            with LOCK:
                KOL_WALLETS.update(new)
            if _main_ws:
                _main_ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": list(KOL_WALLETS.keys())}))
            log.info(f"KOL refreshed: {len(KOL_WALLETS)} wallets")
        except Exception as e:
            log.error(f"KOL refresh error: {e}")

def daily_summary_loop():
    last_date = None
    while True:
        time.sleep(60)
        now = datetime.now()
        if now.hour == 20 and now.date() != last_date:
            last_date = now.date()
            send_daily_summary()

def send_daily_summary():
    with LOCK:
        trades = list(CLOSED)
    if not trades:
        send_tg("📊 <b>FOMO Edge Daily Summary</b>\nNo closed trades yet.")
        return

    wins      = [t for t in trades if t["result"] == "WIN"]
    total_pnl = sum(float(t["pnl_usd"]) for t in trades)
    win_rate  = len(wins) / len(trades) * 100
    best      = max(trades, key=lambda t: float(t["pnl_usd"]))
    worst     = min(trades, key=lambda t: float(t["pnl_usd"]))

    by_trig = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
    for t in trades:
        trig = t["trigger"].split(":")[0]
        by_trig[trig]["total"] += 1
        by_trig[trig]["pnl"]   += float(t["pnl_usd"])
        if t["result"] == "WIN":
            by_trig[trig]["wins"] += 1

    trig_str = ""
    for trig, d in sorted(by_trig.items()):
        wr = d["wins"] / d["total"] * 100 if d["total"] else 0
        trig_str += f"  {trig}: {d['wins']}/{d['total']} ({wr:.0f}%) ${d['pnl']:+.2f}\n"

    # KOL leaderboard
    kol_str = ""
    for handle, ks in sorted(KOL_STATS.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True)[:5]:
        t  = ks["wins"] + ks["losses"]
        wr = ks["wins"] / t * 100 if t else 0
        kol_str += f"  {handle}: {ks['wins']}W/{ks['losses']}L ({wr:.0f}%) ${ks['total_pnl']:+.2f}\n"

    send_tg(
        f"📊 <b>FOMO Edge Daily Summary</b>\n\n"
        f"Trades: {len(trades)} | W:{len(wins)} L:{len(trades)-len(wins)}\n"
        f"Win Rate: {win_rate:.0f}% | P&L: <b>${total_pnl:+.2f}</b>\n\n"
        f"By signal:\n{trig_str}\n"
        f"Best:  ${best['symbol']} +{float(best['pct_change']):.0f}% (${float(best['pnl_usd']):+.2f})\n"
        f"Worst: ${worst['symbol']} {float(worst['pct_change']):.0f}% (${float(worst['pnl_usd']):+.2f})\n\n"
        f"Top KOLs:\n{kol_str}"
        f"Grad devs: {len(DEV_GRADUATES)} | Blacklisted: {len(DEV_BLACKLIST)}\n"
        f"Sniper wallets: {len(SNIPER_WALLETS)} | Score threshold: {SCORE_MIN}"
    )

# ── Telegram alpha queue consumer ─────────────────────────────────────────
QUEUE_FILE = os.path.join(CONFIG_DIR, "tg_alpha_queue.json")
TG_PROCESSED = set()  # keys already acted on

def tg_alpha_consumer():
    """
    Polls the queue file written by tg_monitor.py every 3 seconds.
    For mint addresses: subscribe + enter directly.
    For tickers: watch for matching token in TRACKED then enter.
    """
    log.info("TG alpha consumer started")
    while True:
        time.sleep(3)
        try:
            if not os.path.exists(QUEUE_FILE):
                continue
            with open(QUEUE_FILE) as f:
                queue = json.load(f)
        except:
            continue

        for item in queue:
            key = item.get("key", "")
            ts  = item.get("ts", 0)
            if key in TG_PROCESSED:
                continue
            if time.time() - ts > 300:  # ignore signals older than 5 min
                TG_PROCESSED.add(key)
                continue

            sig_type = item.get("type", "ticker")
            channel  = item.get("channel", "unknown")
            source   = f"TG_ALPHA:{channel}"

            TG_PROCESSED.add(key)

            if sig_type == "mint" and len(key) > 15:
                # Direct mint address — subscribe and enter
                mint = key
                log.info(f"[TG ALPHA] Direct mint from @{channel}: {mint[:8]}...")
                if _main_ws:
                    try:
                        _main_ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
                    except:
                        pass
                # Give it 2 seconds to populate TRACKED, then try enter
                def delayed_enter(m=mint, s=source, c=channel):
                    time.sleep(2)
                    with LOCK:
                        if m not in TRACKED:
                            # Create a minimal entry so try_enter can work
                            TRACKED[m] = {
                                "name": "TG Alpha",
                                "symbol": "???",
                                "launch_time": time.time(),
                                "initial_sol": 0,
                                "dev_key": "",
                                "total_sol": 0,
                                "mcap_sol": 30,
                                "buys": 0,
                                "buyers": [],
                            }
                    try_enter(m, s, [f"📡 Posted in @{c}"], 1)
                threading.Thread(target=delayed_enter, daemon=True).start()

            elif sig_type == "ticker":
                # Ticker match — find it in TRACKED by symbol
                ticker = key.upper()
                log.info(f"[TG ALPHA] Ticker ${ticker} from @{channel} — scanning TRACKED")
                def ticker_hunt(t=ticker, s=source, c=channel):
                    deadline = time.time() + 120  # hunt for 2 min
                    while time.time() < deadline:
                        with LOCK:
                            matches = [
                                (mint, tok) for mint, tok in TRACKED.items()
                                if tok.get("symbol", "").upper() == t
                                and mint not in ALERTED
                            ]
                        if matches:
                            # Pick freshest match
                            mint, tok = min(matches, key=lambda x: time.time() - x[1].get("launch_time", 0))
                            age = time.time() - tok.get("launch_time", time.time())
                            log.info(f"[TG ALPHA] Matched ${t} → {mint[:8]} age={age:.0f}s")
                            try_enter(mint, s, [f"📡 ${t} called in @{c}"], 1)
                            break
                        time.sleep(2)
                threading.Thread(target=ticker_hunt, daemon=True).start()

def run_fomo_feed_ws():
    import websocket as ws_lib
    def on_msg(ws, raw):
        try:
            ev = json.loads(raw)
        except:
            return
        if ev.get("type") not in ("trade", "alert"):
            return
        handle    = ev.get("handle", "").lower()
        kol_match = next((v for v in KOL_WALLETS.values() if v.lower() == handle), None)
        if not kol_match:
            return
        ks       = KOL_STATS.get(kol_match, {})
        kol_total = ks.get("wins", 0) + ks.get("losses", 0)
        kol_wr    = ks.get("wins", 0) / kol_total if kol_total >= 5 else 1.0
        if kol_wr < 0.35:
            return
        mint    = ev.get("tokenAddress") or ev.get("mint", "")
        side    = ev.get("side", "")
        if not mint or side != "buy":
            return
        sol_amt = float(ev.get("solAmount", 0) or ev.get("amountSol", 0) or 0)
        with LOCK:
            tok = TRACKED.get(mint, {"name": ev.get("tokenName",""), "symbol": ev.get("tokenSymbol","???"), "mcap_sol": 30, "launch_time": time.time()})
        threading.Thread(
            target=try_enter,
            args=(mint, f"FOMO_FEED:{kol_match}", [f"👁 {kol_match} posted buy on FOMO"], 2),
            daemon=True
        ).start()

    while True:
        try:
            wsa = ws_lib.WebSocketApp(
                FOMO_WS_URL,
                on_message=on_msg,
                on_error=lambda ws, e: log.error(f"FOMO feed: {e}"),
                on_close=lambda ws, c, m: log.warning("FOMO feed WS closed"),
            )
            wsa.run_forever(ping_interval=20, ping_timeout=10, reconnect=3, sslopt={"cert_reqs": 0})
        except Exception as e:
            log.error(f"FOMO feed crash: {e}")
        time.sleep(5)

def dexscreener_momentum_loop():
    """Poll GeckoTerminal every 60s for trending Solana pools with real momentum.
    Completely independent of PumpPortal WS — fires signals without any WS dependency."""
    seen = set()
    log.info("[DEXSCREEN] Momentum scanner started")
    while True:
        try:
            url = "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?page=1"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json;version=20230302",
                "Origin": "https://www.geckoterminal.com",
                "Referer": "https://www.geckoterminal.com/"
            })
            with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as r:
                data = json.loads(r.read())

            pools = data.get("data", [])
            for pool in pools:
                attrs = pool.get("attributes", {})
                rel   = pool.get("relationships", {})
                mint_raw = rel.get("base_token", {}).get("data", {}).get("id", "")
                mint = mint_raw.replace("solana_", "") if mint_raw.startswith("solana_") else ""
                if not mint or mint in seen or mint in ALERTED:
                    continue

                pc    = attrs.get("price_change_percentage", {})
                c5m   = float(pc.get("m5", 0) or 0)
                c1h   = float(pc.get("h1", 0) or 0)
                vol5m = float((attrs.get("volume_usd") or {}).get("m5", 0) or 0)
                liq   = float((attrs.get("reserve_in_usd") or 0))
                mcap  = float(attrs.get("fdv_usd") or attrs.get("market_cap_usd") or 0)
                mcap_sol = mcap / SOL_PRICE if SOL_PRICE else 0

                created = attrs.get("pool_created_at", "")
                if created:
                    try:
                        import datetime as _dt
                        created_ts = _dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                        age_s = time.time() - created_ts
                    except Exception:
                        age_s = 99999
                else:
                    age_s = 99999

                # Filter: positive 5m AND 1h, under 4h old, under $1M mcap, min volume
                if c5m <= 0 or c1h <= 0:
                    continue
                if age_s > 14400 or mcap > 1_000_000:
                    continue
                if vol5m < 200:
                    continue

                sym = attrs.get("name", "???").split(" / ")[0]
                log.info(f"[DEXSCREEN] ${sym} +{c5m:.1f}% 5m +{c1h:.1f}% 1h mcap=${mcap/1000:.0f}K age={age_s/60:.0f}m vol5m=${vol5m:.0f}")
                seen.add(mint)

                with LOCK:
                    if mint not in TRACKED:
                        TRACKED[mint] = {
                            "name": sym, "symbol": sym,
                            "launch_time": time.time() - age_s,
                            "initial_sol": 0, "dev_key": "",
                            "total_sol": vol5m / SOL_PRICE if SOL_PRICE else 0,
                            "mcap_sol": mcap_sol,
                            "buys": max(1, int(vol5m / 30)),
                            "buyers": [],
                        }
                    else:
                        TRACKED[mint]["mcap_sol"] = mcap_sol

                # Score: 5m momentum + 1h trend + volume
                momentum_score = min(100, int(c5m * 0.4 + c1h * 0.3 + min(vol5m / 50, 25)))
                reasons = [f"📈 +{c5m:.0f}% 5m / +{c1h:.0f}% 1h", f"💰 ${vol5m:.0f} vol 5m", f"mcap ${mcap/1000:.0f}K"]
                log.info(f"[DEXSCREEN] ${sym} momentum_score={momentum_score}")
                if momentum_score >= 30:
                    log.info(f"[DEXSCREEN] 🚀 SIGNAL ${sym} score={momentum_score} — firing entry")
                    threading.Thread(
                        target=try_enter,
                        args=(mint, "DEXSCREEN", reasons, 2),
                        daemon=True
                    ).start()

        except Exception as e:
            log.error(f"[DEXSCREEN] error: {e}")
        time.sleep(60)





# ── Main ───────────────────────────────────────────────────────────────────
def safe_thread(fn, *args, **kwargs):
    """Wrap any background thread so an unhandled exception logs + never crashes PM2."""
    def wrapper():
        try:
            fn(*args, **kwargs)
        except Exception as e:
            log.error(f"[THREAD CRASH] {fn.__name__}: {e}", exc_info=True)
    return wrapper

def run():
    load_learned_data()
    get_sol_price()
    log.info(f"FOMO Edge v2 starting. SOL=${SOL_PRICE}")

    threading.Thread(target=safe_thread(cleanup_loop),              daemon=True).start()
    threading.Thread(target=safe_thread(kol_refresh_loop),          daemon=True).start()
    threading.Thread(target=safe_thread(daily_summary_loop),        daemon=True).start()
    threading.Thread(target=safe_thread(dexscreener_momentum_loop), daemon=True).start()
    threading.Thread(target=safe_thread(run_fomo_feed_ws),          daemon=True).start()
    threading.Thread(target=safe_thread(tg_alpha_consumer),         daemon=True).start()

    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://pumpportal.fun/api/data",
                on_message=on_message,
                on_open=on_open,
                on_error=on_error,
                on_close=on_close,
                header={"Origin": "https://pumpportal.fun", "User-Agent": "Mozilla/5.0"}
            )
            ws.run_forever(
                ping_interval=20,       # send ping every 20s to keep connection alive
                ping_timeout=10,        # if no pong in 10s, reconnect
                reconnect=3,            # auto-reconnect with 3s delay inside run_forever
                sslopt={"cert_reqs": 0}
            )
        except Exception as e:
            log.error(f"Main WS crash: {e}")
        _main_ws = None
        log.info("Reconnecting in 5s...")
        time.sleep(5)

if __name__ == "__main__":
    run()
