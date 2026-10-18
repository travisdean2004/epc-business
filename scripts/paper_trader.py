#!/usr/bin/env python3
"""
FOMO Paper Trader — with KOL Copy Trading
Watches top FOMO traders (Orangie, leaderboard whales) AND scores every new launch.
Paper trades only — no real money. Goal: tune thresholds before going live.
"""

import json, os, sys, time, threading, logging, csv, urllib.request, urllib.error, subprocess
from datetime import datetime, date
from collections import defaultdict
import websocket

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger("paper_trader")

# ── Config ───────────────────────────────────────────────────────────────
FOMO_API_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
FOMO_API_BASE = "https://api.fomoapi.io/v2"
FOMO_WS_ALERTS = f"wss://api.fomoapi.io/ws/alerts?key={FOMO_API_KEY}"

# ── KOL wallet list — Orangie confirmed + top 7d leaderboard wallets ─────
KOL_WALLETS = {
    # Confirmed KOLs
    "83b2LMf12aLec92kur3duRA8VvUkLaXUtML31aCcZNCM": "Orangie",
    # Top 7d leaderboard (Solana wallets only)
    "Beqv6dzTcjV2eodo8RRXCiCcnSYrS1vkQKhfqwHXqeit": "pointfarmcap",
    "2heJbC32Tpfcb3nbUb5ER61K11FGZVfVGtVnDm6LDogF": "unipcs",
    "4ugDhHJ8XDXAeABmrNmGffFaLbJb9BkPyiFGVSV9ocwo": "The__Solstice",
    "F5hkYsi8JxjyA2JHN5CA7MbnnhWubkXB2ZQB7Gkaxqs6": "theveeman",
    "9wMSNoA7TzhwUjqsACVGEvzAxAibCHnsZTgXEAGov8zQ": "frogmanhaha",
    "EC2f5DnHzuNRit1ExqghSifDbp1wgrzktsRRZCtU92MJ": "0xdetweiler",
    "8xL8S7P4QLdTGRquHas8NP5EVjp2qUGbmSgrkh97mvmq": "0xAvast",
    "9LF3d3fxAbeabsxn2GLzMKqNbS1MUMtKvMcNLjTPbDNo": "leo",
    "BA3nKHc4DoSANRrx4FcCupExzs6cWzw1wkPpqjnqJaCN": "AviFelman",
    "jrbGz3zoBJfptXF967xp6h5TBRV55ArvGeWxTQVs5Ux": "ogle",
}

# Refresh KOL list from leaderboard every 6 hours
KOL_LAST_REFRESH = 0
KOL_REFRESH_INTERVAL = 6 * 3600

# Recent KOL buys: wallet → {mint, time} to avoid double-triggering
KOL_RECENT_BUYS = {}

TG_CHAT = "-5051326332"
try:
    TG_BOT = json.load(open(os.path.expanduser("~/epc-webhook/config.json"))).get("TG_BOT_TOKEN", "")
except:
    TG_BOT = ""

LOG_FILE = os.path.expanduser("~/.hermes/paper_trades.csv")
SUMMARY_HOUR = 20  # 8 PM daily summary

# ── Tunable parameters ───────────────────────────────────────────────────
BUY_SCORE_MIN  = 65      # min score to paper-buy
MAX_MCAP_SOL   = 400     # max mcap in SOL at entry (~$60K)
TP_PCT         = 100.0   # take profit %
SL_PCT         = -40.0   # stop loss %
TRADE_SIZE_USD = 5.0     # simulated $ per trade
MAX_OPEN       = 5       # max simultaneous open positions
MONITOR_SECS   = 1800    # stop monitoring after 30 min (force close at current price)

SOL_PRICE = 155.0

# ── State ────────────────────────────────────────────────────────────────
LOCK      = threading.Lock()
TRACKED   = {}         # mint → token data (same as pump_watcher)
BUY_EVENTS = defaultdict(list)
ALERTED   = set()
POSITIONS = {}         # mint → {entry_mcap_sol, entry_time, symbol, name, score, entry_usd}
CLOSED    = []         # list of closed trade dicts
LAST_SUMMARY_DATE = None

# ── Helpers ───────────────────────────────────────────────────────────────
def get_sol_price():
    global SOL_PRICE
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        SOL_PRICE = float(data["solana"]["usd"])
    except:
        pass
    return SOL_PRICE

def send_tg(msg):
    if not TG_BOT:
        log.info(f"[TG] {msg}")
        return
    payload = json.dumps({"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"})
    try:
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
            "-H", "Content-Type: application/json",
            "-d", payload
        ], capture_output=True, timeout=10)
    except:
        pass

def write_trade_log(trade):
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp","symbol","name","mint","score",
            "entry_mcap_usd","exit_mcap_usd","pct_change",
            "trade_usd","pnl_usd","result","hold_secs","reasons"
        ])
        if not file_exists:
            w.writeheader()
        w.writerow(trade)

# ── Scoring (duplicated from pump_watcher for standalone operation) ───────
VIRAL_KEYWORDS = [
    "trump","gta","elon","bitcoin","btc","doge","pepe","cat","dog","maga",
    "fart","ai","rug","solana","sol","pump","moon","wojak","chad","based",
    "cabal","fed","nuke","ape","frog","shib","bonk","wif","money","cash",
    "rich","100x","1000x","gem","whale","meme","viral","tiktok","twitter",
    "orangie","kol","influencer","insider","sniper","laptop","gta6",
]

def has_viral_keyword(name, symbol):
    text = (name + " " + symbol).lower()
    return any(kw in text for kw in VIRAL_KEYWORDS)

def score_launch(mint):
    tok = TRACKED.get(mint, {})
    if not tok:
        return 0, []
    reasons = []
    score = 0
    now = time.time()

    dev_sol = tok.get("initial_sol", 0)
    if dev_sol >= 50:
        score += 60; reasons.append(f"🐳🐳 Dev bought {dev_sol:.1f} SOL — WHALE DEV")
    elif dev_sol >= 20:
        score += 48; reasons.append(f"🐳 Dev bought {dev_sol:.1f} SOL")
    elif dev_sol >= 10:
        score += 35; reasons.append(f"🐳 Dev bought {dev_sol:.1f} SOL")
    elif dev_sol >= 3:
        score += 22; reasons.append(f"💰 Dev bought {dev_sol:.1f} SOL")
    elif dev_sol >= 1:
        score += 13; reasons.append(f"Dev bought {dev_sol:.1f} SOL")
    elif dev_sol >= 0.5:
        score += 6

    recent = [t for t in BUY_EVENTS[mint] if now - t < 60]
    if len(recent) >= 10:
        score += 35; reasons.append(f"🔥🔥🔥 {len(recent)} buys/min")
    elif len(recent) >= 6:
        score += 25; reasons.append(f"🔥🔥 {len(recent)} buys/min")
    elif len(recent) >= 3:
        score += 15; reasons.append(f"🔥 {len(recent)} buys/min")

    total_sol = tok.get("total_sol", 0)
    if total_sol >= 20:
        score += 20; reasons.append(f"💎 {total_sol:.1f} SOL volume")
    elif total_sol >= 8:
        score += 13; reasons.append(f"{total_sol:.1f} SOL volume")
    elif total_sol >= 3:
        score += 7

    unique = len(set(tok.get("buyers", [])))
    if unique >= 15:
        score += 12; reasons.append(f"{unique} unique wallets")
    elif unique >= 8:
        score += 7; reasons.append(f"{unique} unique wallets")
    elif unique >= 4:
        score += 4

    if has_viral_keyword(tok.get("name", ""), tok.get("symbol", "")):
        score += 10; reasons.append(f"📣 Viral name: {tok.get('name')}")

    age = now - tok.get("launch_time", now)
    if age < 120:
        score += 5; reasons.append("⚡ Under 2 min old")

    return min(score, 100), reasons

# ── Paper trade entry ────────────────────────────────────────────────────
def maybe_enter(mint):
    with LOCK:
        if mint in ALERTED or mint in POSITIONS:
            return
        if len(POSITIONS) >= MAX_OPEN:
            return
        tok = TRACKED.get(mint)
        if not tok:
            return
        score, reasons = score_launch(mint)
        mcap_sol = tok.get("mcap_sol", 30)
        if score < BUY_SCORE_MIN or mcap_sol > MAX_MCAP_SOL:
            return
        ALERTED.add(mint)
        entry_mcap_usd = mcap_sol * SOL_PRICE
        POSITIONS[mint] = {
            "entry_mcap_sol": mcap_sol,
            "entry_mcap_usd": entry_mcap_usd,
            "entry_time": time.time(),
            "symbol": tok["symbol"],
            "name": tok["name"],
            "score": score,
            "reasons": reasons[:4],
        }

    log.info(f"[PAPER BUY] ${tok['symbol']} score={score} mcap=${entry_mcap_usd/1e3:.1f}K")
    send_tg(
        f"📝 <b>PAPER BUY</b> — ${tok['symbol']}\n"
        f"{tok['name']}\n\n"
        f"Score: {score}/100\n"
        f"Entry mcap: ${entry_mcap_usd/1e3:.1f}K\n"
        f"Sim trade: ${TRADE_SIZE_USD:.0f}\n"
        f"TP: +{TP_PCT:.0f}%  SL: {SL_PCT:.0f}%\n\n"
        + "\n".join(f"  {r}" for r in reasons[:4]) +
        f"\n\npump.fun/{mint}"
    )

    # Monitor in background
    threading.Thread(target=monitor_position, args=(mint,), daemon=True).start()

def monitor_position(mint):
    start = time.time()
    while True:
        time.sleep(5)
        elapsed = time.time() - start

        with LOCK:
            pos = POSITIONS.get(mint)
            tok = TRACKED.get(mint)
            if not pos or not tok:
                return

            current_mcap_sol = tok.get("mcap_sol", pos["entry_mcap_sol"])
            entry_mcap_sol = pos["entry_mcap_sol"]

        pct = ((current_mcap_sol - entry_mcap_sol) / entry_mcap_sol) * 100
        current_mcap_usd = current_mcap_sol * SOL_PRICE
        pnl_usd = TRADE_SIZE_USD * (pct / 100)

        # Check exit conditions
        reason = None
        if pct >= TP_PCT:
            reason = "TP HIT 🎯"
        elif pct <= SL_PCT:
            reason = "SL HIT 🛑"
        elif elapsed >= MONITOR_SECS:
            reason = "TIMEOUT ⏱"

        if reason:
            close_position(mint, current_mcap_sol, pct, pnl_usd, reason, elapsed)
            return

def close_position(mint, exit_mcap_sol, pct, pnl_usd, reason, hold_secs):
    with LOCK:
        pos = POSITIONS.pop(mint, None)
    if not pos:
        return

    exit_mcap_usd = exit_mcap_sol * SOL_PRICE
    result = "WIN" if pnl_usd > 0 else "LOSS"
    emoji = "✅" if pnl_usd > 0 else "❌"

    trade = {
        "timestamp": datetime.now().isoformat(),
        "symbol": pos["symbol"],
        "name": pos["name"],
        "mint": mint,
        "score": pos["score"],
        "entry_mcap_usd": f"{pos['entry_mcap_usd']:.0f}",
        "exit_mcap_usd": f"{exit_mcap_usd:.0f}",
        "pct_change": f"{pct:.1f}",
        "trade_usd": f"{TRADE_SIZE_USD:.2f}",
        "pnl_usd": f"{pnl_usd:.2f}",
        "result": result,
        "hold_secs": f"{hold_secs:.0f}",
        "reasons": " | ".join(pos.get("reasons", [])),
    }

    with LOCK:
        CLOSED.append(trade)
    write_trade_log(trade)

    log.info(f"[PAPER CLOSE] ${pos['symbol']} {reason} {pct:+.1f}% P&L=${pnl_usd:+.2f}")
    send_tg(
        f"{emoji} <b>PAPER CLOSE</b> — ${pos['symbol']}\n"
        f"{reason}\n\n"
        f"Entry: ${pos['entry_mcap_usd']/1e3:.1f}K → Exit: ${exit_mcap_usd/1e3:.1f}K\n"
        f"Change: {pct:+.1f}%\n"
        f"Sim P&L: <b>${pnl_usd:+.2f}</b>\n"
        f"Hold: {int(hold_secs//60)}m{int(hold_secs%60)}s"
    )

# ── Daily summary ─────────────────────────────────────────────────────────
def daily_summary():
    global LAST_SUMMARY_DATE
    while True:
        time.sleep(60)
        now = datetime.now()
        if now.hour == SUMMARY_HOUR and now.date() != LAST_SUMMARY_DATE:
            LAST_SUMMARY_DATE = now.date()
            send_summary()

def send_summary():
    with LOCK:
        trades = list(CLOSED)

    if not trades:
        send_tg("📊 <b>Paper Trader Daily Summary</b>\nNo trades closed today yet.")
        return

    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    total_pnl = sum(float(t["pnl_usd"]) for t in trades)
    win_rate  = len(wins) / len(trades) * 100

    best  = max(trades, key=lambda t: float(t["pnl_usd"]))
    worst = min(trades, key=lambda t: float(t["pnl_usd"]))

    # Score breakdown
    high_score  = [t for t in trades if int(t["score"]) >= 80]
    mid_score   = [t for t in trades if 65 <= int(t["score"]) < 80]

    msg = (
        f"📊 <b>Paper Trader Daily Summary</b>\n\n"
        f"Trades: {len(trades)} | W: {len(wins)} L: {len(losses)}\n"
        f"Win Rate: {win_rate:.0f}%\n"
        f"Total Sim P&L: <b>${total_pnl:+.2f}</b>\n\n"
        f"Best:  ${best['symbol']} {float(best['pct_change']):+.0f}% (${float(best['pnl_usd']):+.2f})\n"
        f"Worst: ${worst['symbol']} {float(worst['pct_change']):+.0f}% (${float(worst['pnl_usd']):+.2f})\n\n"
        f"Score 80+: {len(high_score)} trades, "
        f"W={len([t for t in high_score if t['result']=='WIN'])}\n"
        f"Score 65-79: {len(mid_score)} trades, "
        f"W={len([t for t in mid_score if t['result']=='WIN'])}\n\n"
        f"Open positions: {len(POSITIONS)}\n"
        f"Current settings: score>={BUY_SCORE_MIN}, TP={TP_PCT:.0f}%, SL={SL_PCT:.0f}%"
    )
    send_tg(msg)

# ── WebSocket handlers ────────────────────────────────────────────────────
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
        if initial_sol >= 5:
            threading.Thread(target=maybe_enter, args=(mint,), daemon=True).start()
        try:
            ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
        except:
            pass

    elif tx_type == "buy":
        # Check if this is a KOL wallet buying
        buyer = data.get("traderPublicKey", "")
        if buyer in KOL_WALLETS:
            with LOCK:
                tok = TRACKED.get(mint, {
                    "name": data.get("name", mint[:8]),
                    "symbol": data.get("symbol", "???"),
                    "mcap_sol": float(data.get("marketCapSol") or data.get("newMarketCapSol") or 30),
                    "launch_time": now,
                })
            sol_amt = float(data.get("solAmount", 0) or 0)
            threading.Thread(target=handle_kol_buy, args=(buyer, mint, sol_amt, tok), daemon=True).start()

        sol_amt  = float(data.get("solAmount", 0) or 0)
        buyer    = data.get("traderPublicKey", "")
        mcap_sol = float(data.get("marketCapSol") or data.get("newMarketCapSol") or 0)
        with LOCK:
            if mint not in TRACKED:
                return
            tok = TRACKED[mint]
            if now - tok.get("launch_time", now) > 900:
                return
            tok["buys"] = tok.get("buys", 0) + 1
            tok["total_sol"] = tok.get("total_sol", 0) + sol_amt
            if buyer and buyer not in tok.get("buyers", []):
                tok.setdefault("buyers", []).append(buyer)
            if mcap_sol:
                tok["mcap_sol"] = mcap_sol
            BUY_EVENTS[mint].append(now)
        threading.Thread(target=maybe_enter, args=(mint,), daemon=True).start()

    elif tx_type == "sell":
        with LOCK:
            if mint in TRACKED:
                sol_amt = float(data.get("solAmount", 0) or 0)
                TRACKED[mint]["total_sol"] = max(0, TRACKED[mint].get("total_sol", 0) - sol_amt * 0.3)
                mcap_sol = float(data.get("marketCapSol") or data.get("newMarketCapSol") or 0)
                if mcap_sol:
                    TRACKED[mint]["mcap_sol"] = mcap_sol

def on_open(ws):
    log.info("Paper trader connected to PumpPortal")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    # Subscribe to all KOL wallet trades
    ws.send(json.dumps({
        "method": "subscribeAccountTrade",
        "keys": list(KOL_WALLETS.keys())
    }))
    log.info(f"Subscribed to {len(KOL_WALLETS)} KOL wallets")
    send_tg(
        f"📝 <b>FOMO Paper Trader LIVE</b>\n\n"
        f"Score threshold: {BUY_SCORE_MIN}+\n"
        f"TP: +{TP_PCT:.0f}% | SL: {SL_PCT:.0f}%\n"
        f"Sim trade size: ${TRADE_SIZE_USD:.0f}\n"
        f"Max open: {MAX_OPEN}\n"
        f"KOLs watched: {len(KOL_WALLETS)} (Orangie + top leaderboard)\n\n"
        "Watching every pump.fun launch + top trader buys. No real money."
    )

def on_error(ws, error):
    log.error(f"WS error: {error}")

def on_close(ws, code, msg):
    log.warning(f"WS closed: {code}")

# ── Cleanup loop ──────────────────────────────────────────────────────────
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
        log.info(f"Cleanup: tracking {len(TRACKED)} tokens, {len(POSITIONS)} open positions")

# ── KOL leaderboard refresh ───────────────────────────────────────────────
def refresh_kol_list():
    global KOL_LAST_REFRESH
    while True:
        time.sleep(60)
        if time.time() - KOL_LAST_REFRESH < KOL_REFRESH_INTERVAL:
            continue
        try:
            req = urllib.request.Request(
                f"{FOMO_API_BASE}/leaderboard/7d?limit=30",
                headers={"authorization": f"Bearer {FOMO_API_KEY}"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            new_wallets = {}
            for t in data.get("traders", []):
                sol = t.get("wallets", {}).get("solana")
                if sol:
                    new_wallets[sol] = t["handle"]
            with LOCK:
                KOL_WALLETS.update(new_wallets)
            KOL_LAST_REFRESH = time.time()
            log.info(f"KOL list refreshed: {len(KOL_WALLETS)} wallets tracked")
            # Re-subscribe on pumpportal WS
            if _pump_ws:
                try:
                    _pump_ws.send(json.dumps({
                        "method": "subscribeAccountTrade",
                        "keys": list(KOL_WALLETS.keys())
                    }))
                except:
                    pass
        except Exception as e:
            log.error(f"KOL refresh error: {e}")

# ── Handle KOL buy events from pumpportal ────────────────────────────────
def handle_kol_buy(wallet, mint, sol_amt, tok_data):
    kol_name = KOL_WALLETS.get(wallet, wallet[:8])
    now = time.time()

    # Dedupe — ignore if we already triggered on this mint from this wallet recently
    key = f"{wallet}:{mint}"
    with LOCK:
        if KOL_RECENT_BUYS.get(key, 0) > now - 120:
            return
        KOL_RECENT_BUYS[key] = now

    name   = tok_data.get("name", mint[:8])
    symbol = tok_data.get("symbol", "???")
    mcap_sol = tok_data.get("mcap_sol", 30)
    mcap_usd = mcap_sol * SOL_PRICE
    age_s = int(now - tok_data.get("launch_time", now))

    log.info(f"[KOL BUY] {kol_name} bought ${symbol} ({sol_amt:.2f} SOL) mcap=${mcap_usd/1e3:.1f}K")

    # Always paper trade KOL buys (bypass score filter) if mcap reasonable
    if mcap_sol <= MAX_MCAP_SOL * 1.5:
        threading.Thread(target=kol_paper_enter, args=(mint, kol_name, sol_amt, tok_data), daemon=True).start()

def kol_paper_enter(mint, kol_name, kol_sol_amt, tok_data):
    with LOCK:
        if mint in POSITIONS or len(POSITIONS) >= MAX_OPEN:
            return
        mcap_sol = tok_data.get("mcap_sol", 30)
        entry_mcap_usd = mcap_sol * SOL_PRICE
        POSITIONS[mint] = {
            "entry_mcap_sol": mcap_sol,
            "entry_mcap_usd": entry_mcap_usd,
            "entry_time": time.time(),
            "symbol": tok_data.get("symbol", "???"),
            "name": tok_data.get("name", mint[:8]),
            "score": 0,
            "reasons": [f"👁 {kol_name} bought {kol_sol_amt:.2f} SOL"],
            "trigger": "KOL",
            "kol": kol_name,
        }
        ALERTED.add(mint)

    send_tg(
        f"👁 <b>KOL COPY — {kol_name}</b>\n"
        f"${tok_data.get('symbol','???')} — {tok_data.get('name', mint[:8])}\n\n"
        f"{kol_name} just bought {kol_sol_amt:.2f} SOL\n"
        f"Entry mcap: ${entry_mcap_usd/1e3:.1f}K\n"
        f"Sim trade: ${TRADE_SIZE_USD:.0f}\n"
        f"TP: +{TP_PCT:.0f}%  SL: {SL_PCT:.0f}%\n\n"
        f"pump.fun/{mint}"
    )
    threading.Thread(target=monitor_position, args=(mint,), daemon=True).start()

# ── FOMO API WebSocket (app-feed alerts) ─────────────────────────────────
def run_fomo_ws():
    """Secondary WS: watches FOMO app feed for KOL trade alerts."""
    import websocket as ws_lib
    def on_msg(ws, raw):
        try:
            ev = json.loads(raw)
        except:
            return
        if ev.get("type") != "trade":
            return
        handle = ev.get("handle", "")
        # Check if this trader is in our KOL list by handle
        kol_name = None
        for w, h in KOL_WALLETS.items():
            if h.lower() == handle.lower():
                kol_name = h
                break
        if not kol_name:
            return
        mint = ev.get("tokenAddress") or ev.get("mint", "")
        if not mint:
            return
        side = ev.get("side", "")
        if side != "buy":
            return
        sol_amt = float(ev.get("solAmount", 0) or ev.get("amountSol", 0) or 0)
        with LOCK:
            tok = TRACKED.get(mint, {"name": ev.get("tokenName",""), "symbol": ev.get("tokenSymbol","???"), "mcap_sol": 30, "launch_time": time.time()})
        threading.Thread(target=handle_kol_buy, args=("fomo_feed", mint, sol_amt, tok), daemon=True).start()

    def on_open(ws):
        log.info("FOMO alert WS connected")

    def on_error(ws, e):
        log.error(f"FOMO WS error: {e}")

    def on_close(ws, code, msg):
        log.warning(f"FOMO WS closed: {code}")

    while True:
        try:
            wsa = ws_lib.WebSocketApp(
                FOMO_WS_ALERTS,
                on_message=on_msg,
                on_open=on_open,
                on_error=on_error,
                on_close=on_close,
            )
            wsa.run_forever(ping_interval=30, ping_timeout=10, reconnect=5,
                            sslopt={"cert_reqs": 0})
        except Exception as e:
            log.error(f"FOMO WS crash: {e}")
        time.sleep(5)

_pump_ws = None

def run():
    global _pump_ws
    get_sol_price()
    log.info(f"Paper trader starting. SOL=${SOL_PRICE} | KOLs: {len(KOL_WALLETS)}")
    threading.Thread(target=cleanup_loop, daemon=True).start()
    threading.Thread(target=daily_summary, daemon=True).start()
    threading.Thread(target=refresh_kol_list, daemon=True).start()
    threading.Thread(target=run_fomo_ws, daemon=True).start()
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
            _pump_ws = ws
            ws.run_forever(ping_interval=30, ping_timeout=10, reconnect=5,
                           sslopt={"cert_reqs": 0})
        except Exception as e:
            log.error(f"Crash: {e}")
        _pump_ws = None
        log.info("Reconnecting in 5s...")
        time.sleep(5)

if __name__ == "__main__":
    run()
