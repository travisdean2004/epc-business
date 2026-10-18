# Automation Stack

## Cron Jobs (Hermes)
All run from ~/.hermes/cron/ via Hermes Agent scheduler

### Every 2 Minutes
- epc_recruit_texter.py — text new recruits
- epc_lead_capture_monitor_autonomous.py — check lead flow
- indeed_lead_failover.py — fallback Indeed scraper

### Every 5 Minutes
- epc_hvac_notifier.py — pull new HVAC leads (Facebook)
- epc_recruiting_notifier.py — pull new recruits (Facebook)
- indeed_scraper_standalone.py — pull Indeed applicants (BLOCKED)
- epc_indeed_cdp_scraper.py — pull via CDP (BLOCKED)
- baps_lead_notifier.py — pull BAPS leads

### Every 30 Minutes
- epc_token_watchdog.py — verify EPC API tokens still valid
- indeed_waf_monitor.sh — check if Indeed WAF still blocking

### Daily
- epc_morning_pulse.py — 7am: daily summary
- epc_nightly_digest.py — 8pm: contractor activity summary
- epc_recruiting_pipeline.py — Monday 7am: pipeline metrics
- sr_kpi_report.py — 8am: SalesRabbit KPI digest
- sr_slacker_alert.py — 2pm: contractor activity alerts

### Weekly
- epc_turf_checkin.py — Monday 7am: new turf batch assignments

## Telegram Channels
1. **EPC HOT LEADS** (-5476036884) — HVAC leads only
2. **NEW HIRES** (-5306696575) — Recruiting applicants
3. **EPC TRADERS** (if active) — Crypto bot trades
4. **Travis DM** (6985623877) — Personal alerts + summaries

## Token Management
- Facebook Graph API tokens (30-day expiry)
- SalesRabbit JWT (30-day refresh)
- Indeed session cookies
- Telegram bot token (permanent, monitor for abuse)
- EPC backend API tokens (custom, check weekly)

## State Files
- ~/.hermes/epc_*_seen_leads.txt — deduplication
- ~/.hermes/indeed_weekend_leads.json — Indeed dedup
- ~/.hermes/sr_web_token.txt — SalesRabbit auth token
- ~/.hermes/epc_recruiting_seen_leads.txt — recruiting dedup
