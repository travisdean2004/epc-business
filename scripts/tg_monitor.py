#!/usr/bin/env python3
"""
FOMO Telegram Alpha Monitor
Watches public alpha channels as a Telegram user.
When a pump.fun link or $TICKER is posted, fires immediately into fomo_edge.
"""

import asyncio, json, os, re, time, logging, subprocess
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityMention, MessageEntityBold

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("tg_monitor")

# ── Credentials ────────────────────────────────────────────────────────────
API_ID   = 33167375
API_HASH = "6c22e984601eab7ee7c137275923d0da"
SESSION  = os.path.expanduser("~/.hermes/tg_monitor_session")

# ── Telegram ───────────────────────────────────────────────────────────────
TG_CHAT = ""  # Silent — no notifications
try:
    TG_BOT = json.load(open(os.path.expanduser("~/epc-webhook/config.json"))).get("TG_BOT_TOKEN", "")
except:
    TG_BOT = ""

# ── Channels to monitor ────────────────────────────────────────────────────
# Add more as you find good ones
WATCH_CHANNELS = [
    "orangiealpha",          # Orangie's free public channel — 16K subs
    "SOL_TRENDING",          # Solana trending data feed
    "memecoin_pump_pumpfun_signalcall",  # 37K free community
    "solanamemecoinss",      # Solana meme calls
]

# ── Patterns to catch ──────────────────────────────────────────────────────
# pump.fun/<mint_address>
PUMPFUN_RE  = re.compile(r"pump\.fun/([A-Za-z0-9]{32,50})")
# $TICKER — 2-10 uppercase chars after $
TICKER_RE   = re.compile(r"\$([A-Z]{2,10})\b")
# Solana mint address — standalone base58 32-50 chars
MINT_RE     = re.compile(r"\b([1-9A-HJ-NP-Za-km-z]{40,50})\b")

# Dedupe: don't fire the same mint twice in 5 min
FIRED = {}   # mint/ticker -> timestamp

# ── Shared state with fomo_edge (via a simple JSON queue file) ────────────
QUEUE_FILE = os.path.expanduser("~/.hermes/tg_alpha_queue.json")

def send_tg(msg):
    if not TG_BOT:
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

def push_alpha(source, mint_or_ticker, msg_text, channel):
    """Push a signal to the queue file for fomo_edge to pick up."""
    now = time.time()
    key = mint_or_ticker.lower()

    # Dedupe within 5 minutes
    if FIRED.get(key, 0) > now - 300:
        return
    FIRED[key] = now

    # Load existing queue
    try:
        queue = json.load(open(QUEUE_FILE))
    except:
        queue = []

    queue.append({
        "source":    source,
        "key":       mint_or_ticker,
        "channel":   channel,
        "text":      msg_text[:300],
        "ts":        now,
        "type":      "mint" if len(mint_or_ticker) > 15 else "ticker",
    })

    with open(QUEUE_FILE, "w") as f:
        json.dump(queue[-50:], f, indent=2)  # keep last 50

    log.info(f"[ALPHA] {source} from @{channel}: {mint_or_ticker}")

    # Alert to FOMO Telegram group immediately
    send_tg(
        f"📡 <b>TG ALPHA — @{channel}</b>\n\n"
        f"Signal: <code>{mint_or_ticker}</code>\n\n"
        f"Message: {msg_text[:200]}\n\n"
        f"{'pump.fun/' + mint_or_ticker if len(mint_or_ticker) > 15 else ''}"
    )

def parse_message(text, channel):
    """Extract pump.fun mints and tickers from message text."""
    if not text:
        return

    signals = []

    # pump.fun links — highest confidence
    for match in PUMPFUN_RE.finditer(text):
        mint = match.group(1)
        signals.append(("PUMPFUN_LINK", mint))

    # $TICKER mentions
    for match in TICKER_RE.finditer(text):
        ticker = match.group(1)
        # Skip common non-coin words
        if ticker in ("SOL", "USD", "USDC", "ETH", "BTC", "NFT", "API", "VIP", "DM"):
            continue
        signals.append(("TICKER", ticker))

    # Standalone Solana addresses (only if no pump.fun link found)
    if not signals:
        for match in MINT_RE.finditer(text):
            addr = match.group(1)
            # Solana addresses are typically 43-44 chars
            if 43 <= len(addr) <= 44:
                signals.append(("MINT_ADDR", addr))

    for sig_type, value in signals[:3]:  # max 3 signals per message
        push_alpha(sig_type, value, text, channel)

async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    log.info("Telegram client connected")

    # Resolve channel entities
    channel_entities = []
    for ch in WATCH_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            channel_entities.append(entity)
            log.info(f"Watching: @{ch} ({entity.title})")
        except Exception as e:
            log.warning(f"Could not resolve @{ch}: {e}")

    if not channel_entities:
        log.error("No channels resolved. Check channel names.")
        return

    entity_ids = {e.id for e in channel_entities}

    send_tg(
        f"📡 <b>TG Alpha Monitor LIVE</b>\n\n"
        f"Watching {len(channel_entities)} channels:\n" +
        "\n".join(f"  • @{ch}" for ch in WATCH_CHANNELS[:len(channel_entities)]) +
        f"\n\nWill alert instantly when pump.fun links or $TICKERS are posted."
    )

    @client.on(events.NewMessage())
    async def handler(event):
        # Only process messages from watched channels
        chat_id = event.chat_id
        # For channels, chat_id is negative
        peer_id = getattr(event.peer_id, "channel_id", None) or \
                  getattr(event.peer_id, "chat_id", None) or \
                  getattr(event.peer_id, "user_id", None)

        # Check if this is one of our watched channels
        matched_channel = None
        for entity in channel_entities:
            if abs(chat_id) == abs(entity.id) or (peer_id and abs(peer_id) == abs(entity.id)):
                matched_channel = entity.username or entity.title
                break

        if not matched_channel:
            return

        text = event.message.text or ""
        if len(text) < 3:
            return

        log.info(f"MSG @{matched_channel}: {text[:80]}")
        parse_message(text, matched_channel)

    log.info(f"Listening for messages on {len(channel_entities)} channels...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
