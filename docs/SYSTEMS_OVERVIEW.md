# EPC Contractors — Systems Overview

## Lead Generation Pipelines

### Facebook HVAC Leads
- **Forms:** 2001630314050736, 36482701701375624, 1048249684207030
- **Notifier:** `epc_hvac_notifier.py` (every 5 min → EPC HOT LEADS chat)
- **Status:** ✅ Live (fixed Oct 18)

### Facebook Recruiting Leads
- **Forms:** Job postings, contractor recruitment
- **Notifier:** `epc_recruiting_notifier.py` (every 5 min → NEW HIRES chat)
- **Status:** ✅ Live

### Indeed Applicants
- **Source:** Indeed employer dashboard
- **Scraper:** `indeed_weekend_leads.py` (weekend-only)
- **Status:** ⚠️ Cloudflare WAF blocking (manual check required)
- **Workaround:** Check Indeed manually Sat-Sun

## Operations

### SalesRabbit Integration
- **KPI Reports:** Daily 8am snapshot (areas, reps, turf performance)
- **Turf Bot:** Auto-assign areas, track coverage
- **Status:** ✅ Deployed

### Telegram Notifications (3-Channel)
1. **EPC HOT LEADS** (-5476036884) — HVAC leads
2. **NEW HIRES** (-5306696575) — Recruiting applicants
3. **Fomo Trading Chat** — Crypto trades

### Crypto Bot (Autonomous)
- **Platform:** FOMO (Solana memecoin trading)
- **Strategy:** Copy Orangie (entry <$1M MC, exits +50%/+100%/+200%, -30% stop)
- **Status:** ✅ Trading live ($2.96 bankroll, live session)

## Key Automations

### Cron Jobs (Every 2-5 Min)
- HVAC notifier
- Recruiting notifier
- Email agent
- Token watchdog (refresh SR JWT)
- Recruit texter
- Indeed scraper (blocked by WAF)
- FOMO bot watchdog
- Geo anti-drift check

### Daily Tasks
- Morning pulse (7am)
- Nightly digest (8pm)
- SalesRabbit KPI report (8am)

## Credentials & Setup

All stored in `~/.hermes/.env`:
- `TG_BOT_TOKEN` — Telegram bot
- `SR_TOKEN` (JWT) — SalesRabbit API
- `FOMO_JWT` — FOMO trading session
- `FACEBOOK_TOKEN` — Meta Business API

## Troubleshooting

### HVAC Notifier Dead
- Check: `cronjob list | grep b6406d1273ac`
- Last run should be <10 min ago
- If stale: `cronjob run b6406d1273ac`

### Indeed Leads Missing
- Cloudflare WAF blocks bot polling
- Manual workaround: https://employers.indeed.com/candidates
- Check "Applied" date for weekend applicants

### Crypto Bot Not Trading
- Check process: `ps aux | grep fomo_orangie`
- Check wallet: 4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn
- Log: `~/.hermes/cron/output/*/`

## Recent Changes (Oct 2026)

- Oct 18: Fixed HVAC notifier (dead 4 days)
- Oct 13-16: Cloudflare WAF investigation (Indeed)
- Oct 12: Crypto bot v4 hardened sell execution
- Oct 9: Autonomous execution mandate (no ask-first)

## Next Improvements

1. **Supabase** — centralized leads DB
2. **n8n** — visual workflow builder
3. **Residential IP** — bypass Indeed Cloudflare
4. **GitHub sync** — auto-deploy from repo
