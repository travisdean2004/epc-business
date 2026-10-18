# Recruiting Pipeline

## Applicant Flow
1. **Source** → Facebook forms OR Indeed applicants
2. **Notified** → NEW HIRES chat (human review)
3. **Auto-Text** → "Thanks for applying to EPC! Call 877-xxx-xxxx to schedule."
4. **Manual Follow-up** → Sales rep calls, schedules site visit
5. **Site Visit** → Field assessment, training offer
6. **Onboard** → SalesRabbit turf assignment, KPI tracking

## Scripts
- `epc_recruiting_notifier.py` — pull new FB recruits (every 5 min)
- `epc_recruit_texter.py` — auto-SMS to new applicants (every 2 min)
- `epc_recruiting_pipeline.py` — weekly pipeline report (Monday 7am)

## SalesRabbit Integration
- All hires assigned turfs in SalesRabbit
- KPI Dashboard: daily contractor stats (calls, estimates, closes)
- Area Finder: generate optimal territories based on density + history
- Turf Monitoring: watch for slackers (0 calls/day alerts)

## Stale Lead Follow-Up
- Wednesday + Friday 2pm: nudge stale leads (no contact for 3+ days)
- Prompt: "Hey, still interested in joining EPC?"
- Auto-escalate to manager if no response

## Success Metrics
- Time from lead → hire (target: 7 days)
- Applicants per week (target: 20+)
- Hire rate (target: 30% of applicants)
- Retention (target: 3+ months)
