# EPC Contractors Website

## Frontend
- Domain: epc-contractors.com (or similar)
- CMS: WordPress (assumed) or static HTML
- Pages: Services, pricing, locations, careers, contact
- Lead form: "Get free estimate" (feeds Facebook ads)

## Backend
- Contact form → email Travis + store in Supabase (planned)
- Appointment booking → SalesRabbit calendar
- Payment processing: Stripe (for deposits/escrow)
- Analytics: Google Analytics + Facebook pixel

## Integration Needed (Future)
- Website form submissions → Supabase (centralized leads DB)
- Auto-notify: NEW HIRES or EPC HOT LEADS Telegram
- Auto-create SalesRabbit lead record
- Track source: direct website vs Facebook vs Indeed

## SEO
- Target keywords: "HVAC contractors near me", "solar installation", "electrician jobs"
- Meta descriptions: job titles + locations
- Local schema markup (business address, hours, reviews)

## Known Issues
- No centralized lead DB (forms scattered across FB, Indeed, website)
- No unified CRM (Travis managing manually)
- No attribution (don't know which ads drive website visitors)
