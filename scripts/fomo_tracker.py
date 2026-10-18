#!/usr/bin/env python3
"""
FOMO Meme Coin Tracker v3 — Dual-source early detection.
Layer 1: GeckoTerminal trending Solana pools (5m/1h momentum, real-time)
Layer 2: FOMO API top trader leaderboard (smart money conviction)
Signal: hot on GeckoTerminal + top traders holding = BUY NOW
"""
import json, os, time, subprocess, urllib.request
from datetime import datetime

_fc = os.path.expanduser("~/.hermes/fomo_config.json")
FOMO_KEY = json.load(open(_fc)).get("fomo_api_key","") if os.path.exists(_fc) else ""
STATE_FILE = os.path.expanduser("~/.hermes/fomo_state.json")
TG_CHAT = "-5051326332"
BANKROLL = 20.0

try:
    TG_BOT = json.load(open(os.path.expanduser("~/epc-webhook/config.json"))).get("TG_BOT_TOKEN","")
except:
    TG_BOT = ""

GECKO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json;version=20230302",
    "Origin": "https://www.geckoterminal.com",
    "Referer": "https://www.geckoterminal.com/"
}

def gecko_get(path):
    req = urllib.request.Request(f"https://api.geckoterminal.com/api/v2{path}", headers=GECKO_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except:
        return {}

def fomo_get(path):
    req = urllib.request.Request(
        f"https://api.fomoapi.io{path}",
        headers={"authorization": f"Bearer {FOMO_KEY}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except:
        return {}

def dex_batch(addresses):
    """DexScreener batch lookup for mcap + extra data."""
    results = {}
    if not addresses:
        return results
    joined = ",".join(addresses[:30])
    req = urllib.request.Request(
        f"https://api.dexscreener.com/latest/dex/tokens/{joined}",
        headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        for pair in data.get("pairs", []):
            addr = pair.get("baseToken", {}).get("address", "").lower()
            if addr and addr not in results:
                pc = pair.get("priceChange", {})
                results[addr] = {
                    "mcap": pair.get("fdv") or pair.get("marketCap") or 0,
                    "change5m": pc.get("m5", 0) or 0,
                    "change1h": pc.get("h1", 0) or 0,
                    "change24h": pc.get("h24", 0) or 0,
                }
    except:
        pass
    return results

def send_tg(msg):
    if not TG_BOT:
        return
    payload = json.dumps({"chat_id": TG_CHAT, "text": msg})
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
        "-H", "Content-Type: application/json", "-d", payload
    ], capture_output=True)

def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def size_bet(conviction, early):
    if conviction >= 75 and early >= 65:
        return 10   # Max — screaming signal
    elif conviction >= 60 and early >= 50:
        return 5
    elif conviction >= 45 and early >= 35:
        return 3
    else:
        return 2

def run():
    state = load_state()
    alerted_buy = state.get("alerted_buy", {})
    alerted_sell = state.get("alerted_sell", {})
    prev_tokens = state.get("tokens", {})
    prev_trader_holdings = state.get("trader_holdings", {})

    # ── LAYER 1: GeckoTerminal trending Solana pools ──────────────────
    gecko_data = {}  # symbol_lower -> attrs
    gt = gecko_get("/networks/solana/trending_pools?page=1")
    for pool in gt.get("data", []):
        attrs = pool.get("attributes", {})
        pc = attrs.get("price_change_percentage", {})
        c5m = float(pc.get("m5", 0) or 0)
        c1h = float(pc.get("h1", 0) or 0)
        c24h = float(pc.get("h24", 0) or 0)
        liq = float(attrs.get("reserve_in_usd") or 0)
        name = attrs.get("name", "").split(" / ")[0].upper()
        txns5m = attrs.get("transactions", {}).get("m5", {})
        buys5m = txns5m.get("buys", 0) if isinstance(txns5m, dict) else 0
        vol5m = float((attrs.get("volume_usd") or {}).get("m5", 0) or 0)
        # Base token address from relationships
        base_id = pool.get("relationships", {}).get("base_token", {}).get("data", {}).get("id", "")
        base_addr = base_id.replace("solana_", "").lower() if base_id else ""

        if name and liq > 3000:
            gecko_data[name] = {
                "c5m": c5m, "c1h": c1h, "c24h": c24h,
                "liq": liq, "buys5m": buys5m, "vol5m": vol5m,
                "addr": base_addr
            }

    # ── LAYER 2: FOMO leaderboard ────────────────────────────────────
    lb = fomo_get("/v2/leaderboard/24h")
    traders = lb.get("traders", [])[:10]

    token_votes = {}
    new_entries = {}
    current_trader_holdings = {}

    for trader in traders:
        tid = trader.get("walletAddress") or str(trader.get("rank", ""))
        prev_held = set(prev_trader_holdings.get(tid, []))
        curr_held = []
        for tok in trader.get("topTokens", []):
            addr = tok.get("tokenAddress", "").lower()
            if not addr:
                continue
            curr_held.append(addr)
            if addr not in token_votes:
                token_votes[addr] = {"count": 0, "total_pnl": 0}
            token_votes[addr]["count"] += 1
            token_votes[addr]["total_pnl"] += tok.get("pnl", 0) or 0
            if addr not in prev_held:
                new_entries[addr] = new_entries.get(addr, 0) + 1
        current_trader_holdings[tid] = curr_held

    # DexScreener data for FOMO tokens
    fomo_addrs = list(token_votes.keys())
    dex_data = dex_batch(fomo_addrs)

    # ── LAYER 3: FOMO trending tokens for symbol mapping ─────────────
    fomo_trending = fomo_get("/v2/leaderboard/tokens/trending?limit=50")
    fomo_sym_map = {}  # symbol_upper -> addr
    for tok in fomo_trending.get("tokens", []):
        sym = tok.get("token", {}).get("symbol", "").upper()
        addr = tok.get("token", {}).get("address", "").lower()
        if sym and addr:
            fomo_sym_map[sym] = addr

    # ── SCORING ───────────────────────────────────────────────────────
    buy_signals = []
    sell_signals = []
    new_tokens = {}
    now = time.time()

    # Score GeckoTerminal tokens (cross-ref with FOMO)
    for sym, gd in gecko_data.items():
        c5m = gd["c5m"]
        c1h = gd["c1h"]
        c24h = gd["c24h"]
        liq = gd["liq"]
        buys5m = gd["buys5m"]
        vol5m = gd["vol5m"]
        addr = gd["addr"] or fomo_sym_map.get(sym, "")

        # Skip if dumping
        if c1h < -10:
            continue
        # Skip if already massively pumped
        if c24h > 2000:
            continue

        # Cross-ref: is this also in FOMO top traders?
        fomo_holders = 0
        is_new_entry = 0
        if addr:
            vote = token_votes.get(addr, {})
            fomo_holders = vote.get("count", 0)
            is_new_entry = new_entries.get(addr, 0)

        # EARLY SCORE — how fresh is this opportunity
        early = 0
        # 5m momentum (most important — is it pumping RIGHT NOW)
        if c5m > 30:     early += 35
        elif c5m > 15:   early += 25
        elif c5m > 8:    early += 16
        elif c5m > 3:    early += 8
        # 1h still has room (not already spent)
        if 0 < c1h < 50:   early += 20  # Moving but not overdone
        elif 0 < c1h < 150: early += 10
        elif c1h > 150:     early += 0   # Already running
        # Recent buying activity
        if buys5m > 30:    early += 15
        elif buys5m > 15:  early += 10
        elif buys5m > 5:   early += 5
        # Volume in last 5m (money flowing in NOW)
        if vol5m > 50000:  early += 10
        elif vol5m > 10000: early += 6
        elif vol5m > 2000:  early += 3
        # Penalty if already way up on 24h
        if c24h > 500:   early -= 20
        elif c24h > 200: early -= 10
        early = max(0, min(early, 100))

        # CONVICTION — smart money backing
        conviction = 0
        conviction += min(fomo_holders * 20, 40)   # Top traders holding
        conviction += min(is_new_entry * 15, 30)    # New entries this scan
        if c5m > 15:   conviction += 15
        elif c5m > 5:  conviction += 8
        if buys5m > 20: conviction += 10
        conviction = min(conviction, 100)

        # Need at least some momentum
        if early < 20 or c5m <= 0:
            continue

        key = addr or sym
        mcap = 0
        if addr:
            mcap = dex_data.get(addr, {}).get("mcap", 0)

        mcap_s = f"${mcap/1e6:.1f}M" if mcap >= 1e6 else f"${mcap/1e3:.0f}K" if mcap > 0 else "?"

        new_tokens[key] = {
            "symbol": sym, "conviction": conviction, "early": early,
            "c5m": c5m, "c1h": c1h, "c24h": c24h, "mcap": mcap,
            "fomo_holders": fomo_holders, "buys5m": buys5m
        }

        prev = prev_tokens.get(key, {})

        # BUY signal: must be moving up NOW (positive 5m) + early score
        if early >= 40 and c5m > 2 and key not in alerted_buy:  # min early:40 = no LATE alerts
            amt = size_bet(conviction, early)
            buy_signals.append((early + conviction, sym, amt, c5m, c1h, c24h, fomo_holders, early, conviction, mcap_s, key))
            alerted_buy[key] = {"symbol": sym, "conviction": conviction, "early": early, "ts": now}

        # SELL: was a buy, now dumping
        elif key in alerted_buy and c5m < -10 and c1h < -15 and key not in alerted_sell:
            sell_signals.append((sym, c24h, key))
            alerted_sell[key] = now

    # ── SEND ALERTS ───────────────────────────────────────────────────
    for combined, sym, amt, c5m, c1h, c24h, fomo_h, early, conv, mcap_s, key in sorted(buy_signals, key=lambda x: -x[0])[:3]:
        if early >= 70:
            emoji, tag = "🚀🚀🚀", "EARLY — GET IN NOW"
        elif early >= 50:
            emoji, tag = "🚀🚀", "EARLY"
        elif early >= 30:
            emoji, tag = "🔥", "MID PUMP"
        else:
            emoji, tag = "🔥", "MID PUMP"  # if it passed threshold it's at least mid

        fomo_line = f" | {fomo_h} top traders" if fomo_h > 0 else ""
        msg = (
            f"{emoji} BUY ${amt} of ${sym} — {tag}\n"
            f"5m: {c5m:+.0f}% | 1h: {c1h:+.0f}% | 24h: {c24h:+.0f}%\n"
            f"{mcap_s}{fomo_line}\n"
            f"Early: {early}/100 | Signal: {conv}/100"
        )
        send_tg(msg)

    for sym, c24h, key in sell_signals[:3]:
        send_tg(f"🔴 SELL ${sym} NOW — momentum dead")

    # Summary at :00 and :30
    minute = datetime.now().minute
    if minute < 5 or (29 < minute < 35):
        top = sorted(new_tokens.items(), key=lambda x: x[1]["early"] + x[1]["conviction"], reverse=True)[:5]
        if top:
            lines = [f"📊 FOMO TOP PICKS — ${BANKROLL:.0f} bankroll\n"]
            for key, t in top:
                sym = t["symbol"]
                c5m = t["c5m"]
                c1h = t["c1h"]
                c24h = t["c24h"]
                early = t["early"]
                mcap = t["mcap"]
                fh = t["fomo_holders"]
                mcap_s = f"${mcap/1e6:.1f}M" if mcap >= 1e6 else f"${mcap/1e3:.0f}K" if mcap > 0 else "?"
                tag = "🚀EARLY" if early >= 60 else "🔥MID" if early >= 30 else "⚠️LATE"
                fomo_tag = f" | {fh}🧠" if fh > 0 else ""
                lines.append(f"${sym} | 5m:{c5m:+.0f}% 1h:{c1h:+.0f}% | {mcap_s}{fomo_tag} | {tag}")
            send_tg("\n".join(lines))

    # Cleanup stale alerts (2h)
    alerted_sell = {k: v for k, v in alerted_sell.items() if now - v < 7200}
    active = set(new_tokens.keys())
    alerted_buy = {k: v for k, v in alerted_buy.items() if k in active or now - v.get("ts", 0) < 3600}

    save_state({
        "tokens": new_tokens,
        "alerted_buy": alerted_buy,
        "alerted_sell": alerted_sell,
        "trader_holdings": current_trader_holdings,
        "bankroll": BANKROLL,
        "last_run": datetime.now().strftime("%I:%M %p")
    })

if __name__ == "__main__":
    run()
