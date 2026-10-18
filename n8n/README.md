# n8n Setup (When Ready)

n8n is a visual automation tool. Instead of writing scripts, you drag + drop workflows.

## What Each Workflow Does

1. **Lead Capture** — New Facebook lead → instant Telegram alert
2. **Indeed Monitor** — Check Indeed every 5 min → post new applicants
3. **Crypto Trading** — Copy Orangie's trades → execute automatically

## To Deploy

1. Install n8n: `npm install -g n8n` then `n8n` (runs on localhost:5678)
2. Import workflow JSONs from this folder
3. Connect credentials (Telegram token, FOMO API, etc.)
4. Enable each workflow

## For Now

All workflows run via cron jobs (scripts/). n8n is optional visual alternative.
