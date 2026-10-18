# Common Issues & Fixes

## HVAC Notifier Not Running
1. Check: `hermes cron list | grep HVAC`
2. Last run date > 10 min ago?
3. Check logs: `tail ~/.hermes/epc_webhook_watchdog.log`
4. Fix: `hermes cron run b6406d1273ac` (force run)
5. If still stuck: restart gateway (`pkill -f hermes_cli`)

## Indeed Leads Missing (Oct 18)
- **Root cause:** Cloudflare WAF blocking bot access
- **Workaround:** Manual login + check applicants
- **Timeline:** WAF block expires ~Oct 20
- **Permanent fix:** Residential proxy or Indeed API access

## SalesRabbit Token Expired (401)
1. Run: `python3 ~/.hermes/scripts/sr_token_refresh.py`
2. Or manual: browser → login → copy JWT from DevTools
3. Save to: `~/.hermes/sr_web_token.txt`
4. Verify: `curl -H "Authorization: Bearer ..." https://capi.salesrabbit.com/v1/me`

## Facebook API Rate Limited
- Wait 1 hour
- Reduce script frequency (e.g., every 10 min instead of 5)
- Upgrade FB app tier if budget allows

## Telegram Bot Not Posting
1. Check token in .env: `grep TELEGRAM ~/.hermes/.env`
2. Test: `curl -X POST https://api.telegram.org/bot{TOKEN}/sendMessage -d "..."`
3. If 401: regenerate bot token in BotFather
4. Check chat IDs (may have changed if group renamed)

## Leads Duplicating Across Chats
- Check seen_leads.json files
- If corruption: delete stale entries, Hermes regenerates on next run
- Verify: `wc -l ~/.hermes/epc_*_seen_leads.txt`
