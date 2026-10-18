# Scripts Index

## Lead Generation (Facebook)
- `epc_hvac_notifier.py` — Pull HVAC leads (every 5 min) → EPC HOT LEADS
- `epc_recruiting_notifier.py` — Pull recruiter applicants (every 5 min) → NEW HIRES
- `baps_lead_notifier.py` — Pull BAPS leads (every 5 min)

## Recruiting
- `epc_recruit_texter.py` — Auto-SMS new applicants (every 2 min)
- `epc_recruiting_pipeline.py` — Weekly pipeline report (Monday 7am)

## Indeed Integration
- `indeed_scraper_standalone.py` — Selenium scraper (BROKEN — needs auth)
- `epc_indeed_cdp_scraper.py` — Chrome CDP scraper (BLOCKED by WAF)
- `indeed_weekend_leads.py` — Weekend-only applicants (new Oct 18)
- `indeed_lead_failover.py` — Fallback scraper (every 2 min)

## SalesRabbit
- `sr_kpi_report.py` — Daily KPI digest (8am)
- `sr_slacker_alert.py` — Activity monitoring (2pm)
- `sr_midday_check.py` — Noon check-in (paused)
- `sr_token_watchdog.py` — Token validity check (every 30 min)
- `sr_area_finder.py` — Optimal turf generation

## Monitoring & Health
- `epc_token_watchdog.py` — Verify API tokens (every 30 min)
- `epc_geo_watchdog.py` — Contractor location drift (every 6h)
- `indeed_waf_monitor.sh` — Check Indeed WAF block status (every 30 min)
- `epc_webhook_watchdog.py` — System health (every 5 min)

## Reporting & Summaries
- `epc_morning_pulse.py` — Daily 7am summary
- `epc_nightly_digest.py` — Daily 8pm digest
- `epc_dashboard_data.py` — Collect metrics for dashboard
- `epc_recruiting_fb_post.py` — Auto-post recruiting ads (paused)

## Email Automation
- `epc_email_agent.py` — Facebook form → personalized email (every 180 min)

## Crypto Bot
- `fomo_orangie_auto_trader.py` — Copy-trade Orangie (every 1 min)
- `fomo_bot_watchdog.py` — Bot health monitor (every 2 min)
- `fomo_orangie_live_v4_production.py` — Live trading bot (8am daily)

## Turf Management
- `epc_turf_checkin.py` — Batch turf assignments (Monday 7am)
- `epc_geo_drift_check.py` — Location validation

## Utilities
- `epc_indeed_token_refresh.py` — Refresh session cookies
- `sr_token_refresh.py` — Refresh SalesRabbit JWT
- `facebook_token_refresh.py` — Refresh Graph API token

---

**Total Scripts:** 35+  
**Active (enabled):** 20+  
**Paused:** 5  
**Broken (need fixes):** 3
