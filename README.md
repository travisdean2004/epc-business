# EPC Contractors — Lead Generation & Automation

Integrated lead capture, recruitment, and operations platform for EPC Contractors.

## Structure

- **scripts/** — Automation workflows (lead gen, notifiers, scrapers)
  - `leads/` — Lead capture & processing
  - `recruitment/` — Recruiting pipeline
  - `hvac/` — HVAC lead generation (Facebook)
  - `indeed/` — Indeed applicant scraping
  - `facebook/` — Facebook forms & lead gen
- **docs/** — Runbooks, API references, troubleshooting
- **config/** — Credentials, environment setup

## Key Systems

- Facebook lead gen (HVAC, Recruiting)
- Indeed applicant monitoring
- Telegram notifications (3-channel: HVAC, Recruiting, Email)
- SalesRabbit integration
- Cron-based automation (every 2-5 min)

## Recent Work

- Fixed HVAC notifier (Oct 18) — was dead 4 days
- Indeed Cloudflare WAF blocking (Oct 18) — needs residential IP
- Crypto bot automation (Solana FOMO trading)

## Quick Start

See docs/ for setup guides.
