# Lead Generation Pipeline

## Sources
1. **Facebook HVAC Lead Forms** (IDs: 2001630314050736, 36482701701375624, 1048249684207030)
   - Notifier: epc_hvac_notifier.py (every 5 min)
   - Destination: EPC HOT LEADS chat (-5476036884)
   - Format: Name | Phone | Email | Timestamp

2. **Facebook Recruiting Forms**
   - Forms: Multiple EPC Contractors page lead gens
   - Notifier: epc_recruiting_notifier.py (every 5 min)
   - Destination: NEW HIRES chat (-5306696575)
   - Texting: epc_recruit_texter.py (auto-text new recruits)

3. **Indeed Applicants**
   - Job board: EPC Contractors recruiting campaigns
   - CDP Scraper: epc_indeed_cdp_scraper.py (every 5 min)
   - Issue: Cloudflare WAF blocks automated access (manual workaround)
   - Destination: NEW HIRES chat
   - Fallback: Weekend-only manual check

4. **Facebook Ads Flow**
   - Ad account: Meta Business
   - Lead gen campaigns: HVAC + Recruiting
   - Budget: Variable (track in SalesRabbit)
   - Conversion: Lead → SMS → Phone call → Job site visit → Hire

## Lead Deduplication
- Seen leads tracked in JSON files (~/.hermes/epc_*_seen_leads.txt)
- Key format: name|email or name|phone
- Prevents duplicate Telegram posts

## Metrics Tracked
- Daily new leads (HVAC vs Recruiting)
- Cost per lead (Facebook ad spend / leads)
- Conversion rate (leads → site visits)
- Hire rate (visits → employees)
