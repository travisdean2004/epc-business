#!/usr/bin/env python3
"""
PumpFun Early Launch Watcher — Highest level.
Watches every single new pump.fun launch in real time.
Scores each one. When buy velocity spikes → instant Telegram alert.
Goal: catch coins at $5K-$50K mcap before they run to $500K+
"""
import json, os, time, threading, subprocess, urllib.request, logging
from datetime import datetime
from collections import defaultdict
import websocket

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────
TG_CHAT = "-5051326332"
try:
    TG_BOT = json.load(open(os.path.expanduser("~/epc-webhook/config.json"))).get("TG_BOT_TOKEN","")
except:
    TG_BOT = ""

ALERTED = set()
TRACKED = {}
BUY_EVENTS = defaultdict(list)
LOCK = threading.Lock()
SOL_PRICE = 155.0

# ── Thresholds ────────────────────────────────────────────────────────
MIN_DEV_BUY_SOL = 0.5
MIN_BUYS_PER_MIN = 3
MAX_MCAP_SOL_ALERT = 600   # ~$60K — tighter cap, catch earlier
VIRAL_KEYWORDS = [
    "trump","gta","elon","bitcoin","btc","doge","pepe","cat","dog","maga",
    "fart","ai","rug","solana","sol","pump","moon","wojak","chad","based",
    "cabal","fed","nuke","ape","frog","shib","bonk","wif","money","cash",
    "rich","100x","1000x","gem","whale","meme","viral","tiktok","twitter",
    "orangie","kol","influencer","insider","sniper","laptop","gta6","based",
]

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
        return
    payload = json.dumps({"chat_id": TG_CHAT, "text": msg})
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
        "-H", "Content-Type: application/json",
        "-d", payload
    ], capture_output=True, timeout=10)

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

    # Dev buy size — most important signal
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

    # Buy velocity — buys in last 60s
    recent = [t for t in BUY_EVENTS[mint] if now - t < 60]
    if len(recent) >= 10:
        score += 35; reasons.append(f"🔥🔥🔥 {len(recent)} buys in last 60s")
    elif len(recent) >= 6:
        score += 25; reasons.append(f"🔥🔥 {len(recent)} buys in last 60s")
    elif len(recent) >= 3:
        score += 15; reasons.append(f"🔥 {len(recent)} buys in last 60s")

    # Total SOL flowing in
    total_sol = tok.get("total_sol", 0)
    if total_sol >= 20:
        score += 20; reasons.append(f"💎 {total_sol:.1f} SOL total buy volume")
    elif total_sol >= 8:
        score += 13; reasons.append(f"{total_sol:.1f} SOL buy volume")
    elif total_sol >= 3:
        score += 7

    # Unique buyers (not just one whale)
    unique = len(set(tok.get("buyers", [])))
    if unique >= 15:
        score += 12; reasons.append(f"{unique} unique wallets buying")
    elif unique >= 8:
        score += 7; reasons.append(f"{unique} unique wallets")
    elif unique >= 4:
        score += 4

    # Viral name/ticker
    if has_viral_keyword(tok.get("name",""), tok.get("symbol","")):
        score += 10; reasons.append(f"📣 Trending name: {tok.get('name')}")

    # Freshness bonus
    age = now - tok.get("launch_time", now)
    if age < 120:
        score += 5; reasons.append("⚡ Under 2 min old")

    return min(score, 100), reasons

def check_alert(mint):
    with LOCK:
        if mint in ALERTED:
            return
        tok = TRACKED.get(mint)
        if not tok:
            return
        score, reasons = score_launch(mint)
        mcap_sol = tok.get("mcap_sol", 30)
        if mcap_sol > MAX_MCAP_SOL_ALERT or score < 35:
            return
        ALERTED.add(mint)

    mcap_usd = mcap_sol * SOL_PRICE
    age_s = int(time.time() - tok.get("launch_time", time.time()))
    age_str = f"{age_s}s" if age_s < 120 else f"{age_s//60}m{age_s%60}s"

    if score >= 70:
        emoji, urgency = "🚀🚀🚀", "GET IN NOW"
    elif score >= 50:
        emoji, urgency = "🚀🚀", "EARLY ENTRY"
    else:
        emoji, urgency = "🔥", "WATCH IT"

    reason_str = "\n".join(f"  {r}" for r in reasons[:4])

    msg = (
        f"{emoji} ${tok['symbol']} — {urgency}\n"
        f"{tok['name']}\n"
        f"\n"
        f"Mcap: ${mcap_usd/1e3:.0f}K | Age: {age_str}\n"
        f"Score: {score}/100\n"
        f"\n"
        f"{reason_str}\n"
        f"\n"
        f"pump.fun/{mint}"
    )
    send_tg(msg)
    log.info(f"ALERTED: ${tok['symbol']} score={score} mcap=${mcap_usd/1e3:.0f}K")

def on_message(ws, message):
    try:
        data = json.loads(message)
    except:
        return

    tx_type = data.get("txType")
    mint = data.get("mint", "")
    if not mint:
        return

    now = time.time()

    if tx_type == "create":
        name = data.get("name", "")
        symbol = data.get("symbol", "")
        if not name or not symbol:
            return

        initial_sol = float(data.get("solAmount", 0) or 0)
        mcap_sol = float(data.get("marketCapSol", 30) or 30)
        dev_key = data.get("traderPublicKey", "")

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

        log.info(f"NEW: ${symbol} ({name}) dev={initial_sol:.2f}SOL mcap={mcap_sol:.0f}SOL")

        # Big dev buy = alert immediately
        if initial_sol >= 5:
            threading.Thread(target=check_alert, args=(mint,), daemon=True).start()

        # Subscribe to this token's trades for velocity tracking
        try:
            ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
        except:
            pass

    elif tx_type == "buy":
        sol_amt = float(data.get("solAmount", 0) or 0)
        buyer = data.get("traderPublicKey", "")
        mcap_sol = float(data.get("marketCapSol") or data.get("newMarketCapSol") or 0)

        with LOCK:
            if mint not in TRACKED:
                return
            tok = TRACKED[mint]
            age = now - tok.get("launch_time", now)
            if age > 900:  # ignore > 15 min old
                return
            tok["buys"] = tok.get("buys", 0) + 1
            tok["total_sol"] = tok.get("total_sol", 0) + sol_amt
            if buyer and buyer not in tok.get("buyers", []):
                tok.setdefault("buyers", []).append(buyer)
            if mcap_sol:
                tok["mcap_sol"] = mcap_sol
            BUY_EVENTS[mint].append(now)

        threading.Thread(target=check_alert, args=(mint,), daemon=True).start()

    elif tx_type == "sell":
        with LOCK:
            if mint in TRACKED:
                sol_amt = float(data.get("solAmount", 0) or 0)
                TRACKED[mint]["total_sol"] = max(0, TRACKED[mint].get("total_sol", 0) - sol_amt * 0.3)

def on_open(ws):
    log.info("Connected to PumpPortal")
    ws.send(json.dumps({"method": "subscribeNewToken"}))
    send_tg("🟢 Pump watcher LIVE — watching every pump.fun launch in real time")

def on_error(ws, error):
    log.error(f"WS error: {error}")

def on_close(ws, code, msg):
    log.warning(f"WS closed: {code}")

def cleanup_loop():
    while True:
        time.sleep(300)
        get_sol_price()
        cutoff = time.time() - 1800
        with LOCK:
            old = [m for m, t in TRACKED.items() if t.get("launch_time", 0) < cutoff]
            for m in old:
                TRACKED.pop(m, None)
                BUY_EVENTS.pop(m, None)
        log.info(f"Cleanup done. Tracking {len(TRACKED)} active tokens.")

def run():
    get_sol_price()
    log.info(f"SOL price: ${SOL_PRICE}")
    threading.Thread(target=cleanup_loop, daemon=True).start()
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
            ws.run_forever(ping_interval=30, ping_timeout=10, reconnect=5)
        except Exception as e:
            log.error(f"Crash: {e}")
        log.info("Reconnecting in 5s...")
        time.sleep(5)

if __name__ == "__main__":
    run()
