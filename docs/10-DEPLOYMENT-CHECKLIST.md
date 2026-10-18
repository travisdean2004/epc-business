# Deployment & Setup

## Initial Setup (Mac)
1. [ ] Git installed (`git --version`)
2. [ ] Python 3.11+ (`python3 --version`)
3. [ ] Hermes Agent installed and running
4. [ ] Chrome DevTools port 9222 open (for CDP)
5. [ ] SSH keys configured (for GitHub)
6. [ ] .env file with credentials:
   - FACEBOOK_TOKEN
   - TELEGRAM_BOT_TOKEN
   - SALESRABBIT_JWT
   - INDEED_SESSION (if webhook dies)

## Token Management
- Facebook Graph API: renew every 30 days
- SalesRabbit JWT: renew every 30 days
- Telegram bot token: check monthly for abuse
- Store ALL tokens in ~/.hermes/.env (not in code)

## Cron Job Activation
1. `hermes cron list` — view all jobs
2. For new jobs: `hermes cron create --schedule "*/5 * * * *" --prompt "..." --script "path/to/script.py"`
3. Monitor: check ~/.hermes/cron/output/ for errors

## GitHub Sync
- All scripts committed to https://github.com/travisdean2004/epc-business
- Pull latest: `git pull` before troubleshooting
- Deploy fix: `git commit -am "fix: ..." && git push`
- Hermes pulls on startup

## Scaling (Future)
- Supabase: centralized leads DB (replace JSON files)
- n8n: visual workflows (no code automations)
- MCP: standardized API layer
- Docker: containerize for team deployment
