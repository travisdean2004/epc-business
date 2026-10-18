# Health Checks & Monitoring

## Critical Systems
1. **HVAC Notifier** — must run every 5 min (if dead, leads lost)
2. **Recruiting Notifier** — must run every 5 min
3. **SalesRabbit Token** — must be valid (refresh 30 days)
4. **Facebook API** — rate limits, token expiry
5. **Telegram Bot** — must be live (no infinite hangups)
6. **Indeed Access** — check for WAF blocks daily

## Watchdog Patterns
- epc_token_watchdog.py (every 30 min) — verify auth tokens
- epc_geo_watchdog.py (every 6h) — check contractor locations (SalesRabbit)
- indeed_waf_monitor.sh (every 30 min) — ping Indeed, alert if 403/blocked

## Alert Thresholds
- 0 HVAC leads for 2+ hours → escalate
- 0 recruiting leads for 4+ hours → escalate
- SalesRabbit API 401 → refresh token immediately
- Indeed Cloudflare WAF block → notify Travis (manual check needed)

## Telegram Alert Format
- 🔥 ALERT: [system] [issue] [action taken]
- Example: "🔥 ALERT: HVAC notifier dead 2h. Restarted."

## Silent Watchdog Rule (Oct 16)
- Watchdog jobs NEVER send status updates
- ONLY alert on genuine emergency (system actually broken)
- Fix automatically if possible
- One-sentence alert if must escalate to Travis
