#!/usr/bin/env python3
"""
EPC Command Center Status Generator
Reads Hermes cron jobs and writes /tmp/epc_activity.json for the dashboard.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

JOBS_FILE = Path.home() / '.hermes' / 'cron' / 'jobs.json'
OUT_FILE = Path('/tmp/epc_activity.json')

AGENT_META = {
    "EPC SEO Content Agent": {
        "nickname": "SEO Sam",
        "color": "#e74c3c",
        "emoji": "✍️",
        "mission": "Writes and publishes a daily morning blog article to epc-contractors.org targeting high-value FL solar/roofing keywords.",
    },
    "EPC Daily Facebook Page Publisher": {
        "nickname": "Social Mike",
        "color": "#1976d2",
        "emoji": "📱",
        "mission": "Writes and posts a daily morning Facebook post to EPC Solar FL page via the Graph API.",
    },
    "EPC Meta Ads Intelligence Agent": {
        "nickname": "Ads Alicia",
        "color": "#7b1fa2",
        "emoji": "📊",
        "mission": "Analyzes competitor Meta ads in Tampa Bay area. Finds winning angles, CTAs, and offers EPC should test.",
    },
    "EPC Competitor Scout — Morning Intel": {
        "nickname": "Scout Sam",
        "color": "#00796b",
        "emoji": "🔍",
        "mission": "Scouts competitor solar companies in Pinellas/Hillsborough county. Reports new content, offers, and market moves.",
    },
    "EPC Afternoon Blog Post — 2nd Daily Article": {
        "nickname": "Blog Bot",
        "color": "#f57c00",
        "emoji": "📝",
        "mission": "Publishes a second SEO blog article in the afternoon to maximize daily content output on epc-contractors.org.",
    },
    "EPC Group Content Agent — Daily Posts": {
        "nickname": "Group Gary",
        "color": "#2e7d32",
        "emoji": "👥",
        "mission": "Posts educational solar/energy content to Florida Solar Savings & Energy Tips Facebook group to build community.",
    },
    "EPC Evening Facebook Post — 6PM Engagement": {
        "nickname": "Evening Eddie",
        "color": "#fbc02d",
        "emoji": "🌆",
        "mission": "Posts an evening engagement Facebook post at peak audience hours (6PM ET) to drive comments and reach.",
    },
    "EPC Daily WOW Report — 8PM Travis Briefing": {
        "nickname": "Report Rita",
        "color": "#c2185b",
        "emoji": "📋",
        "mission": "Compiles Travis's nightly briefing — what got done today, wins, opportunities, and tomorrow's plan.",
    },
    "EPC Ad Quality Control Agent": {
        "nickname": "QC Quincy",
        "color": "#eceff1",
        "emoji": "✅",
        "mission": "Reviews all outgoing content before it reaches Travis. Checks for quality, accuracy, tone, and compliance.",
    },
    "EPC Overnight Growth Agent": {
        "nickname": "Night Ninja",
        "color": "#283593",
        "emoji": "🌙",
        "mission": "Runs overnight growth tasks — researching leads, markets, SEO gaps, and opportunities while Travis sleeps.",
    },
    "Revenue Radar": {
        "nickname": "Revenue Radar",
        "color": "#f97316",
        "emoji": "🎯",
        "mission": "Runs every 3 hours. Finds leads, drafts Google review responses, scouts competitor social content, identifies FL homeowner communities. Always produces copy-paste-ready output.",
    },
    "Content Factory": {
        "nickname": "Content Factory",
        "color": "#06b6d4",
        "emoji": "🏭",
        "mission": "Runs every 3 hours. Researches trending FL solar/roofing topics, finds keyword gaps, drafts blog outlines and Facebook post ideas. Feeds the publishing pipeline 24/7.",
    },
    "Growth Intel": {
        "nickname": "Growth Intel",
        "color": "#84cc16",
        "emoji": "📡",
        "mission": "Runs every 3 hours. Monitors Meta Ad Library for competitor ads, tracks FL solar market changes (utility rates, incentives), and flags real growth opportunities with data.",
    },
}

def fmt_time(ts_str):
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        # Convert to ET display
        return ts.strftime('%b %d @ %-I:%M%p').replace('AM','am').replace('PM','pm')
    except:
        return ts_str

def run():
    if not JOBS_FILE.exists():
        print(f"Jobs file not found: {JOBS_FILE}")
        return

    with open(JOBS_FILE) as f:
        raw = json.load(f)

    jobs = raw if isinstance(raw, list) else raw.get('jobs', [])

    agents = []
    for job in jobs:
        name = job.get('name', '')
        meta = AGENT_META.get(name, {})
        
        last_run = job.get('last_run_at')
        next_run = job.get('next_run_at')
        last_status = job.get('last_status')
        enabled = job.get('enabled', True)
        paused = job.get('paused_at') is not None

        if paused:
            status = 'paused'
        elif last_status == 'ok':
            status = 'ok'
        elif last_status == 'error':
            status = 'error'
        elif last_run:
            status = 'ok'
        else:
            status = 'scheduled'

        agents.append({
            "job_id": job.get('job_id'),
            "name": name,
            "nickname": meta.get('nickname', name),
            "color": meta.get('color', '#3b82f6'),
            "emoji": meta.get('emoji', '🤖'),
            "mission": meta.get('mission', 'Autonomous EPC agent.'),
            "schedule": job.get('schedule', ''),
            "last_run": fmt_time(last_run),
            "last_run_raw": last_run,
            "next_run": fmt_time(next_run),
            "next_run_raw": next_run,
            "status": status,
            "enabled": enabled,
            "paused": paused,
        })

    output = {
        "generated_at": datetime.now().isoformat(),
        "agents": agents,
        "total": len(agents),
        "active": sum(1 for a in agents if a['status'] == 'ok'),
        "errors": sum(1 for a in agents if a['status'] == 'error'),
    }

    with open(OUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Written {len(agents)} agents to {OUT_FILE}")

if __name__ == '__main__':
    run()
