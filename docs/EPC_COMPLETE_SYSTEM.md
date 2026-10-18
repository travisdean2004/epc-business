# EPC Contractors — Complete System Documentation

## Lead Capture Pipeline

### Facebook Lead Gen
- **HVAC Forms** (3 IDs): 2001630314050736, 36482701701375624, 1048249684207030
  - Posts to: EPC HOT LEADS Telegram (-5476036884)
  - Notifier: `epc_hvac_lead_notifier.py` (every 5 min)
  - Status: Fixed Oct 18 (was dead 4 days)

- **Recruiting Forms** 
  - Posts to: NEW HIRES Telegram (-5306696575)
  - Notifier: `epc_recruiting_notifier.py` (every 5 min)
  - Status: Working ✅

### Indeed Applicants
- Job ID: 6186a8e3e50c
- Status: **WAF-BLOCKED** (Cloudflare) — need manual check or residential IP
- Workaround: Check applicants manually on mobile/different IP

### Email Outreach
- Agent: `epc_email_agent.py` (every 180 min)
- Pulls Facebook leads → sends pain-focused emails
- Status: Enabled but stale (last run Oct 12)

## Recruiting Workflow

### Lead Routing
1. Facebook form → HVAC notifier → EPC HOT LEADS chat
2. Lead enters text sequence (auto-responder)
3. Follow-up nudges (Wed/Fri 2pm)
4. Weekly pipeline report (Mon 7am)
5. Auto FB posts (Mon/Wed/Fri/Sun 9am)

### SalesRabbit Integration
- Account: splitmudallc@gmail.com / Travi$2485
- Sync: Manual (CDP scraper exists but WAF-blocked)
- Turf Management: Temple Terrace (area 1395) created Oct 16
- KPI Reports: Daily at 8am (paused Sep 19)

## Sales/Turf System

### Area Management
- Turf generation: pocket MH roads, standalone mode
- Anti-drift watchdog: every 6 hours
- Rep tracking per area

### SalesRabbit
- CRM for rep tracking
- Area assignment
- KPI monitoring

## Crypto Trading (Live)
- Platform: FOMO (travisdean2004@icloud.com | Quantum123!)
- Wallet: 4nKMFXa6LPSRxU4n6ihZ9uhpdWoGuRdqMdpMvFwisBgn
- Strategy: Copy Orangie (+$450K/mo) — entry <$1M MC, exits +50%/+100%/+200%, -30% stop
- Status: Trading autonomously, bankroll $2.96 live

## Automation Infrastructure

### Cron Jobs (34 total)
| Job | Schedule | Status |
|-----|----------|--------|
| HVAC notifier | */5 min | ✅ Fixed |
| Recruiting notifier | */5 min | ✅ Working |
| Email agent | every 180 min | ⚠️ Stale |
| Token watchdog | */30 min | ✅ Running |
| Turf checkin | 7am M-F | ✅ Working |
| Morning pulse | 7am daily | ✅ Working |
| Nightly digest | 8pm M-Sat | ✅ Working |
| Crypto bot watchdog | */2 min | ✅ Running |
| FOMO auto-trader | */1 min | ✅ Running |

### Deployment
- Gateway: `hermes gateway run` (PID 1645)
- Chrome CDP: port 9222 (/tmp/epc_chrome)
- Session persistence: ~/.hermes/scripts/

## Known Blockers

1. **Indeed Cloudflare WAF** — IP flagged after bot polling
   - Solution: Wait 24-48h OR use residential VPN OR check manually
   - Workaround: Weekend leads only (manual check)

2. **Facebook Apple SSO** — requires Touch ID/Face ID on device
   - Solution: User approves on iPhone/Mac, agent continues
   - Cannot automate: system-level WebAuthn dialog

3. **SalesRabbit Auth0** — React form blocks direct automation
   - Solution: JWT cookie extraction method (fast, 2-3 min)
   - Reference: `epc-salesrabbit` skill

4. **Phantom Wallet** — extension popup unautomatable
   - Solution: Use Jupiter DEX API or Solana web3.js directly

## System Health Checklist

- [ ] HVAC notifier running (check last_run_at in cron)
- [ ] Recruiting notifier running
- [ ] Email agent enabled + recent run
- [ ] Chrome CDP healthy (port 9222 responsive)
- [ ] Token watchdog refreshing (check logs)
- [ ] Crypto bot trading (check FOMO account)
- [ ] All Telegram chats receiving notifications

## GitHub Sync

All scripts mirrored in: `https://github.com/travisdean2004/epc-business`

Update flow:
1. Commit changes to GitHub
2. Hermes pulls latest
3. Redeploy scripts/cron jobs
4. Monitor via `hermes cron list`

## Skills Used

- `epc-autonomy-style` — autonomous execution discipline
- `epc-desktop-automation` — browser/desktop automation (CDP, cliclick)
- `epc-salesrabbit` — SalesRabbit API workflows
- `epc-lead-capture-systems` — lead gen architecture
- `crypto-trading-execution` — FOMO bot setup
- `github` — repo management

## Contact / Escalation

- **HVAC leads missing?** Check notifier (b6406d1273ac)
- **Recruiting silent?** Check FB form IDs + recruiting notifier
- **Indeed leads?** Manual check (WAF-blocked, use phone)
- **Crypto bot stuck?** Check FOMO account + bot process
- **SalesRabbit sync?** Use JWT cookie extraction method
