#!/usr/bin/env python3
"""
ORANGIE COPY TRADER - JUPITER DEX (Solana On-Chain)
===================================================
Oct 12, 2026

APPROACH: Don't use FOMO UI (mobile-only). 
Trade directly on Jupiter DEX via Solana RPC.
Monitor Orangie's wallet on-chain, execute swaps via Jupiter API.

ENTRY: Watch Orangie's wallet for buys, copy immediately
EXIT: Fixed ladder (+50%, +100%, +200%) + trailing stop
"""

import requests
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "orangie_jupiter.log"
TRADES_FILE = Path.home() / ".hermes" / "orangie_jupiter_trades.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# Orangie's known wallet
ORANGIE_WALLET = "6atxM2LoHbHxPzVzk2BpDqJvJdCfXdGTJG6PQqwFPDU2"
USER_WALLET = "4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn"

# Solana RPC
RPC_URL = "https://api.mainnet-beta.solana.com"
JUPITER_API = "https://quote-api.jup.ag/v6"

CONFIG = {
    "bankroll_usd": 2.96,
    "position_size_usd": 0.30,
    "max_mc": 1_000_000,
}

class Position:
    def __init__(self, token_mint, entry_price, size_usd):
        self.token_mint = token_mint
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.peak_price = entry_price
        self.tiers_sold = [False, False, False]
        self.entry_time = datetime.now()
        self.realized_pnl = 0.0

class OrangieJupiterBot:
    def __init__(self):
        self.positions = {}
        self.bankroll = CONFIG["bankroll_usd"]
        self.session = requests.Session()
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def log(self, msg, level="INFO"):
        getattr(log, level.lower())(msg)

    def log_trade(self, data):
        with open(TRADES_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")

    def get_token_price(self, token_mint):
        """Get current token price from Jupiter"""
        try:
            # Jupiter price API
            url = f"{JUPITER_API}/price?ids={token_mint}"
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and token_mint in data["data"]:
                    return float(data["data"][token_mint]["price"])
        except:
            pass
        return None

    def get_swap_quote(self, input_mint, output_mint, amount_usd):
        """Get Jupiter swap quote"""
        try:
            # Convert USD to lamports (simplified)
            input_amount = int(amount_usd * 1e9)  # Assume 1 SOL = $1 USD for demo
            
            url = f"{JUPITER_API}/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": input_amount,
                "slippageBps": 500,  # 5% slippage
            }
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            self.log(f"Quote error: {e}", "DEBUG")
        return None

    def execute_swap(self, quote):
        """Execute Jupiter swap (in real environment, needs signing)"""
        # In production: Sign transaction with private key, submit to network
        # For now: Log the intent
        return True

    def scan_orangie_wallet(self):
        """Monitor Orangie's wallet for recent transactions"""
        try:
            # RPC call to get recent transactions
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [ORANGIE_WALLET, {"limit": 5}]
            }
            resp = self.session.post(RPC_URL, json=payload, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if "result" in data and data["result"]:
                    # Parse transactions
                    # In production: decode instructions, detect buys
                    return data["result"]
        except Exception as e:
            self.log(f"Wallet scan error: {e}", "DEBUG")
        return []

    def buy_token(self, token_mint, entry_price):
        """Execute buy via Jupiter"""
        try:
            size = CONFIG["position_size_usd"]
            
            # Get quote SOL → Token
            quote = self.get_swap_quote("So11111111111111111111111111111111111111112", token_mint, size)
            if quote:
                # Execute (simplified - real version needs wallet signing)
                self.execute_swap(quote)
                
                self.bankroll -= size
                self.positions[token_mint] = Position(token_mint, entry_price, size)
                self.total_trades += 1
                
                self.log(f"🟢 BUY: {token_mint[:8]}... | ${size:.2f} @ ${entry_price:.9f}", "INFO")
                self.log_trade({
                    "timestamp": datetime.now().isoformat(),
                    "action": "BUY",
                    "token": token_mint,
                    "entry_price": entry_price,
                    "size": size
                })
                return True
        except Exception as e:
            self.log(f"Buy error: {e}", "ERROR")
        return False

    def sell_token(self, token_mint, amount_usd, tier_name):
        """Execute sell via Jupiter"""
        try:
            # Get quote Token → SOL
            quote = self.get_swap_quote(token_mint, "So11111111111111111111111111111111111111112", amount_usd)
            if quote:
                self.execute_swap(quote)
                
                pos = self.positions[token_mint]
                pnl = amount_usd * 0.02  # Placeholder
                
                self.log(f"💰 SELL ({tier_name}): {token_mint[:8]}... | ${amount_usd:.2f} | PnL: +${pnl:.3f}", "INFO")
                self.log_trade({
                    "timestamp": datetime.now().isoformat(),
                    "action": "SELL",
                    "token": token_mint,
                    "tier": tier_name,
                    "amount": amount_usd,
                    "pnl": pnl
                })
                
                if pnl > 0:
                    self.wins += 1
                else:
                    self.losses += 1
                
                pos.realized_pnl += pnl
                self.bankroll += amount_usd + pnl
                
                return True
        except Exception as e:
            self.log(f"Sell error: {e}", "ERROR")
        return False

    def monitor_exits(self):
        """Monitor positions for tier exits"""
        for token_mint in list(self.positions.keys()):
            pos = self.positions[token_mint]
            current_price = self.get_token_price(token_mint)
            
            if not current_price:
                continue
            
            if current_price > pos.peak_price:
                pos.peak_price = current_price
            
            multiple = current_price / pos.entry_price
            
            # Fixed ladder exits
            tiers = [
                (1.50, 0, "+50%"),
                (2.00, 1, "+100%"),
                (3.00, 2, "+200%"),
            ]
            
            for tier_multiple, idx, tier_name in tiers:
                if not pos.tiers_sold[idx] and multiple >= tier_multiple:
                    exit_amount = pos.size_usd * 0.25
                    self.sell_token(token_mint, exit_amount, tier_name)
                    pos.tiers_sold[idx] = True
            
            # Hard stop -30%
            if multiple <= 0.70:
                remaining = pos.size_usd * (1 - sum(pos.tiers_sold) * 0.25)
                if remaining > 0:
                    self.sell_token(token_mint, remaining, "STOP_LOSS")
                del self.positions[token_mint]

    def run(self):
        self.log("=" * 80)
        self.log("🚀 ORANGIE COPY TRADER (Jupiter DEX on Solana)")
        self.log("=" * 80)
        self.log(f"Bankroll: ${self.bankroll:.2f}")
        self.log(f"Position size: ${CONFIG['position_size_usd']:.2f}")
        self.log(f"Monitoring: {ORANGIE_WALLET[:8]}...")
        self.log("=" * 80)
        
        iteration = 0
        while True:
            try:
                iteration += 1
                
                # Scan Orangie's wallet for buys
                txns = self.scan_orangie_wallet()
                
                # Monitor open positions
                self.monitor_exits()
                
                # Status every 100 iterations
                if iteration % 100 == 0:
                    pnl = sum(p.realized_pnl for p in self.positions.values())
                    self.log(f"📊 Bankroll: ${self.bankroll:.2f} | PnL: ${pnl:+.2f} | Trades: {self.total_trades} | Open: {len(self.positions)}", "INFO")
                
                # If bankroll low, stop
                if self.bankroll < 0.30:
                    self.log("❌ Bankroll depleted", "ERROR")
                    break
                
                asyncio.run(asyncio.sleep(3))
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log(f"Cycle error: {e}", "ERROR")
        
        pnl = sum(p.realized_pnl for p in self.positions.values())
        self.log(f"Final: ${self.bankroll:.2f} | PnL: ${pnl:+.2f} | W/L: {self.wins}/{self.losses}", "INFO")

if __name__ == "__main__":
    bot = OrangieJupiterBot()
    bot.run()
