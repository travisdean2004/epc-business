#!/usr/bin/env python3
import requests, json, time, logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "fomo_live_trades.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_live_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
LOG = logging.getLogger(__name__)

FOMO_KEY = "fapi_8d8b3a117f7e47d086e9261a5ee4e4f165ddcd8ac8cb4366a0b7cc0205afd1a2"
JUPITER_URL = "https://api.jup.ag/v1"
BANKROLL = 2.96
POS_SIZE = 0.30

positions = {}
bankroll = BANKROLL
trades_made = 0

def buy_coin(token_addr, amount_usd):
    global bankroll, trades_made
    try:
        # Get price from Jupiter
        r = requests.get(f"{JUPITER_URL}/quote", params={"inputMint":"So11111111111111111111111111111111111111112", "outputMint":token_addr, "amount":int(amount_usd * 1e9)}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            bankroll -= amount_usd
            positions[token_addr] = {"entry_time": datetime.now(), "size": amount_usd}
            trades_made += 1
            LOG.info(f"🟢 BUY {token_addr[:8]}... | ${amount_usd:.2f}")
            with open(TRADES_FILE, "a") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "BUY", "token": token_addr, "size": amount_usd}) + "\n")
            return True
    except:
        pass
    return False

def sell_coin(token_addr, amount_usd):
    global bankroll, trades_made
    try:
        bankroll += amount_usd
        del positions[token_addr]
        trades_made += 1
        LOG.info(f"💰 SELL {token_addr[:8]}... | ${amount_usd:.2f}")
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(), "action": "SELL", "token": token_addr, "size": amount_usd}) + "\n")
        return True
    except:
        pass
    return False

def scrape_fomo_tokens():
    """Scrape trending tokens from FOMO"""
    try:
        r = requests.get("https://fomo.family/api/tokens/trending", headers={"Authorization": f"Bearer {FOMO_KEY}"}, timeout=5)
        if r.status_code == 200:
            tokens = r.json().get("tokens", [])
            return [t.get("address") or t.get("mint") for t in tokens[:10]]
    except:
        pass
    return []

LOG.info("=" * 70)
LOG.info("🚀 FOMO LIVE TRADING (Auto-buy trending, exit after 5min)")
LOG.info("=" * 70)
LOG.info(f"Bankroll: ${bankroll:.2f} | Position size: ${POS_SIZE:.2f}")

start = datetime.now()
seen = set()

while (datetime.now() - start).total_seconds() < 600:  # 10 min test
    # Get trending coins
    tokens = scrape_fomo_tokens()
    for token in tokens:
        if token not in seen and token not in positions and len(positions) < 2:
            if buy_coin(token, POS_SIZE):
                seen.add(token)
    
    # Auto-sell after 5 min
    for token in list(positions.keys()):
        if (datetime.now() - positions[token]["entry_time"]).total_seconds() > 300:
            sell_coin(token, POS_SIZE)
    
    elapsed = (datetime.now() - start).total_seconds() / 60
    if elapsed > 0 and int(elapsed * 10) % 5 == 0:
        pnl = bankroll - BANKROLL
        LOG.info(f"📊 [{int(elapsed)}m] Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades_made} | Open:{len(positions)}")
    
    time.sleep(2)

pnl = bankroll - BANKROLL
LOG.info("=" * 70)
LOG.info(f"TEST COMPLETE | Bank:${bankroll:.2f} | PnL:${pnl:+.2f} | Trades:{trades_made}")
LOG.info("=" * 70)
