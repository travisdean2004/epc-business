# Indeed Recruiting

## Setup
- Account: travisdeanepc04@gmail.com
- Job ID: 6186a8e3e50c (EPC Contractors - Sales Rep)
- Posting: "Make $80K+ independent contractor, HVAC/solar experience"
- Job board: Indeed + job aggregators (ZipRecruiter, CareerBuilder)

## Lead Capture
1. **Webhook Setup** (attempted Oct 13-16)
   - Cloudflare WAF blocks webhook endpoint
   - Solution: Fallback to polling

2. **CDP Scraper** (attempted, WAF blocked)
   - epc_indeed_cdp_scraper.py uses Chrome DevTools
   - Pulls candidate list every 5 min
   - Issue: IP 47.206.162.60 flagged after bot activity
   - Blocker: Cloudflare WAF — 24-48h block (Oct 18)

3. **Manual Check** (current workaround)
   - Login to Indeed dashboard manually
   - View applicants (no automation possible while blocked)
   - Copy names + contact info
   - Paste into NEW HIRES chat

## Applicant Data
- Name, email, phone (sometimes)
- Resume text (scrapeable)
- Applied date/time
- Source: Indeed organic + job board syndication

## Weekend Filter (Oct 18)
- New script: indeed_weekend_leads.py
- Only posts applicants who applied Sat-Sun
- Deduplicates by name|email
- Sends to NEW HIRES chat on Monday morning

## WAF Block Workaround (Until Oct 20)
1. Use residential VPN (slow, not recommended)
2. Wait 24-48h for block to expire
3. Contact Indeed support (unlikely to respond fast)
4. Switch to manual daily checks

## Future Improvements
- Residential proxy service ($ per month)
- Indeed API access (if available)
- Third-party lead aggregator (ZipRecruiter API)
