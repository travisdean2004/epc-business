#!/usr/bin/env python3
"""AGGRESSIVE 1-HOUR TEST - Real FOMO prices, paper trades, loose entry filters"""
import requests, json, time, logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "fomo_aggressive_test.log"
TRADES_FILE = Path.home() / ".hermes" / "fomo_aggressive_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
                   handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger()

FOMO_API_BASE = "https://api.fomo.family"
BANKROLL = 2.96

class Bot:
    def __init__(self):
        self.bankroll = BANKROLL
        self.positions = {}
        self.trades = 0
        self.wins = 0
        self.start = datetime.now()
        self.session = requests.Session()
    
    def get_tokens(self):
        try:
            r = self.session.get(f"{FOMO_API_BASE}/tokens/trending", params={"limit":100}, timeout=5)
            if r.status_code == 200:
                return r.json().get("tokens", [])
        except: pass
        return []
    
    def get_info(self, mint):
        try:
            r = self.session.get(f"{FOMO_API_BASE}/tokens/{mint}", timeout=5)
            if r.status_code == 200:
                return r.json()
        except: pass
        return None
    
    def get_chart(self, mint, limit=20):
        try:
            r = self.session.get(f"{FOMO_API_BASE}/tokens/{mint}/chart", 
                               params={"interval":"1m", "limit":limit}, timeout=5)
            if r.status_code == 200:
                return r.json().get("candles", [])
        except: pass
        return []
    
    def scan(self):
        """AGGRESSIVE: Low bar for entry"""
        tokens = self.get_tokens()
        for t in tokens[:50]:
            mint = t.get("mint")
            mc = t.get("marketCap", 0)
            
            if mc > 5_000_000 or mint in self.positions:
                continue
            
            candles = self.get_chart(mint, limit=10)
            if len(candles) < 3:
                continue
            
            # AGGRESSIVE FILTERS: Very loose
            vol_avg = sum(c.get("volume",0) for c in candles[:-1]) / max(1, len(candles)-1)
            vol_ratio = candles[-1].get("volume", 0) / max(0.0001, vol_avg)
            price_chg = (candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"] * 100 if candles[-2]["close"] > 0 else 0
            
            # Entry: Vol 1.2x+ OR Price 2%+ (VERY loose)
            if vol_ratio >= 1.2 or price_chg >= 2.0:
                self.buy(mint, candles[-1]["close"], mc)
    
    def buy(self, mint, price, mc):
        size = min(0.30, self.bankroll * 0.5)
        if size < 0.10:
            return
        
        self.bankroll -= size
        self.positions[mint] = {"entry": price, "size": size, "peak": price, "tiers": [0,0,0]}
        self.trades += 1
        
        log.info(f"🟢 BUY: {mint[:8]} ${size:.2f} @ ${price:.8f} MC:${mc/1e6:.1f}M")
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps({"t":"BUY", "coin":mint, "size":size, "price":price, "ts":datetime.now().isoformat()}) + "\n")
    
    def monitor(self):
        for mint in list(self.positions.keys()):
            info = self.get_info(mint)
            if not info:
                continue
            
            price = info.get("price", 0)
            if price <= 0:
                continue
            
            pos = self.positions[mint]
            pos["peak"] = max(pos["peak"], price)
            mult = price / pos["entry"]
            
            # Fixed exits
            for i, target in enumerate([1.50, 2.00, 3.00]):
                if pos["tiers"][i] == 0 and mult >= target:
                    amt = pos["size"] * 0.25
                    pnl = amt * (mult - 1)
                    self.bankroll += amt * mult
                    pos["tiers"][i] = 1
                    self.wins += 1
                    log.info(f"💰 SELL ({['+50%','+100%','+200%'][i]}): {mint[:8]} PnL:${pnl:+.3f}")
                    with open(TRADES_FILE, "a") as f:
                        f.write(json.dumps({"t":"SELL", "coin":mint, "tier":i, "pnl":pnl, "ts":datetime.now().isoformat()}) + "\n")
            
            # Hard stop
            if mult <= 0.70:
                amt = pos["size"] * (1 - sum(pos["tiers"])*0.25)
                if amt > 0:
                    pnl = amt * (mult - 1)
                    self.bankroll += amt * mult
                    log.info(f"🔴 STOP: {mint[:8]} PnL:${pnl:+.3f}")
                del self.positions[mint]
    
    def run(self):
        log.info("="*60)
        log.info("🚀 AGGRESSIVE 1HR TEST (Real FOMO coins, loose entry)")
        log.info("="*60)
        
        iteration = 0
        while True:
            elapsed = (datetime.now() - self.start).total_seconds() / 60
            if elapsed >= 60:
                break
            
            iteration += 1
            self.scan()
            self.monitor()
            
            if iteration % 50 == 0:
                pnl = self.bankroll - BANKROLL
                log.info(f"📊 [{elapsed:.0f}m] Bank:${self.bankroll:.2f} PnL:${pnl:+.2f} Trades:{self.trades} W:{self.wins} Open:{len(self.positions)}")
            
            time.sleep(1)
        
        pnl = self.bankroll - BANKROLL
        log.info("="*60)
        log.info(f"DONE. Final:${self.bankroll:.2f} PnL:${pnl:+.2f} W:{self.wins} Trades:{self.trades}")
        log.info("="*60)

if __name__ == "__main__":
    Bot().run()
