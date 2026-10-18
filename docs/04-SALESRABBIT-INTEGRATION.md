# SalesRabbit System

## What It Is
SalesRabbit = contractor field management platform
- Assign territories (turfs) to contractors
- Track KPIs: calls, estimates, closes
- Auto-generate area recommendations (optimal density)
- Time tracking, lead management, payment processing

## Integration Points

### 1. Turf Assignment
- New hire joins EPC → assigned small turf in SalesRabbit
- Turf based on: population density, recent lead history, contractor skill
- Auto-expand if contractor hitting KPI targets

### 2. KPI Dashboard
- Daily sync: pulls contractor stats from SR API
- Metrics: calls/day, estimates/day, close rate, revenue
- Alerts: if contractor hits 0 calls (prob slacking)
- Report: emailed daily 8am to Travis + managers

### 3. Area Finder
- Analyzes: zip code density, past lead performance, competition
- Recommends: optimal turf boundaries for new contractors
- Input: contractor address, skill level
- Output: GeoJSON polygon or address list

### 4. Turf Monitoring
- Every 2 hours: check contractor activity
- If 0 calls for 8+ hours → escalate alert
- Auto-pause lazy contractors (cut leads until they call)

## API Auth
- Endpoint: https://capi.salesrabbit.com/v1/
- Auth: Bearer JWT token (refresh every 30 days)
- Scope: full turf + KPI read/write

## Scripts
- `sr_kpi_report.py` — daily 8am KPI digest
- `sr_area_finder.py` — generate turf recommendations
- `sr_slacker_alert.py` — monitor activity (2pm daily)
- `sr_turf_monitor.py` — real-time slack detection (every 2h)

## Known Issues
- Token refresh needed monthly (manual or cron)
- API rate limits: 100 req/min (build in delays)
- Slow: area finder query can take 30sec (async)
