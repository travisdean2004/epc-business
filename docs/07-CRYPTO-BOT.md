# Solana Memecoin Trading Bot (Orangie Copy-Trade)

## Current Setup
- Platform: FOMO.family
- Strategy: Copy Orangie's FOMO trades exactly
- Bankroll: $2.96 USD (live)
- Entry: <$1M market cap memecoins
- Exit: +50%, +100%, +200%, -30% hard stop, 24h timeout

## Authentication
- Email: travisdean2004@icloud.com
- Password: Quantum123!
- Wallet: 4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn
- Auth Method: JWT cookie (not email/password — Apple SSO blocks headless)

## Automation
- Cron job: fomo-orangie-auto-trader (every 1 min)
- Monitors: Orangie's FOMO leaderboard + recent trades
- Executes: Instant buy on trending coins, auto-sell at targets
- API: Jupiter DEX (Solana swap infrastructure)

## Performance Target
- Orangie: +$450K/mo (verified)
- Our target: 10% of Orangie = +$45K/mo
- Current: Testing phase, small bankroll to learn

## Trades Posted To
- FOMO Trading Chat (internal tracking)
- Hermes DM (Travis confirmation)

## Known Issues
- Headless login to FOMO blocks on Apple SSO (manual approval needed)
- FOMO API rate limits (queue trades, don't spam)
- Jupiter DEX slippage (memecoins liquidity thin)
- Small bankroll = low profit margin (need $500+ to be meaningful)

## Future Plans
- Increase bankroll to $1K+ (when confident)
- Add risk management (position sizing, portfolio diversification)
- Monitor Orangie + 2-3 other top traders (reduce single-point-of-failure)
