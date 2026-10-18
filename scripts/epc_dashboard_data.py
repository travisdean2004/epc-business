#!/usr/bin/env python3
"""
EPC Dashboard Data Generator
Reads cron job output files and writes /tmp/epc_data.json
Run as a no-agent cron job every 30 minutes.
"""
import json, os, re
from datetime import datetime, timezone
from pathlib import Path

CRON_OUTPUT = Path.home() / ".hermes/cron/output"
OUT_FILE = Path("/tmp/epc_data.json")

AGENTS = [
    {"id": "dfb77430fa0f", "name": "SEO Sam",      "role": "Morning Blog Agent",          "schedule": "8AM",  "color": "#e74c3c", "emoji": "✍️"},
    {"id": "9f9ea8dd681f", "name": "Social Mike",  "role": "Facebook Page Publisher",     "schedule": "9AM",  "color": "#1976d2", "emoji": "📱"},
    {"id": "ce195e012b4b", "name": "Ads Alicia",   "role": "Meta Ads Intelligence",       "schedule": "9AM",  "color": "#7b1fa2", "emoji": "📊"},
    {"id": "f0aa8085a5b8", "name": "Scout Sam",    "role": "Competitor Morning Intel",    "schedule": "7AM",  "color": "#00796b", "emoji": "🔍"},
    {"id": "95a9cd0e78b5", "name": "Blog Bot",     "role": "Afternoon Blog Article",      "schedule": "2PM",  "color": "#f57c00", "emoji": "📝"},
    {"id": "e43b4f951a06", "name": "Group Gary",   "role": "Facebook Group Content",      "schedule": "10AM", "color": "#2e7d32", "emoji": "👥"},
    {"id": "6151f85c6d3f", "name": "Evening Eddie","role": "6PM Facebook Post",           "schedule": "6PM",  "color": "#fbc02d", "emoji": "🌆"},
    {"id": "993d6ade3321", "name": "Report Rita",  "role": "Nightly WOW Briefing",        "schedule": "9PM",  "color": "#c2185b", "emoji": "📋"},
    {"id": "67f8b1284c7e", "name": "QC Quincy",    "role": "Quality Control Agent",       "schedule": "9AM",  "color": "#607d8b", "emoji": "✅"},
    {"id": "d931f5fff3a7", "name": "Night Ninja",  "role": "Overnight Growth Agent",      "schedule": "1AM",  "color": "#283593", "emoji": "🌙"},
    {"id": "proactivity",  "name": "Praxis",       "role": "24/7 Proactivity Agent",      "schedule": "Every 3h", "color": "#10b981", "emoji": "⚡"},
]

def parse_output_file(filepath):
    """Extract the agent response section from a cron output .md file."""
    try:
        text = filepath.read_text(errors='replace')
        # Get everything after ## Response
        if "## Response" in text:
            response = text.split("## Response")[-1].strip()
            # Strip leading ---
            response = re.sub(r'^[\s\-]+', '', response).strip()
        else:
            response = text.strip()
        return response
    except Exception as e:
        return f"Could not read file: {e}"

def get_agent_data(agent):
    job_dir = CRON_OUTPUT / agent["id"]
    result = dict(agent)
    result["runs"] = []
    result["last_run_at"] = None
    result["last_status"] = "never"
    result["last_summary"] = "No runs yet"
    result["full_output"] = ""

    if not job_dir.exists():
        return result

    files = sorted(job_dir.glob("*.md"), reverse=True)
    for f in files[:5]:  # last 5 runs
        content = parse_output_file(f)
        # Parse timestamp from filename like 2026-06-16_18-01-00.md
        ts_str = f.stem  # e.g. 2026-06-16_18-01-00
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
            ts_display = dt.strftime("%b %d at %I:%M %p")
            ts_iso = dt.isoformat()
        except:
            ts_display = ts_str
            ts_iso = ts_str

        # Extract first meaningful line as summary
        lines = [l.strip() for l in content.split('\n') if l.strip() and not l.startswith('#')]
        summary = lines[0][:120] if lines else content[:120]

        run_entry = {
            "timestamp": ts_display,
            "ts_iso": ts_iso,
            "summary": summary,
            "full_output": content[:8000],  # cap at 8k chars
            "status": "ok" if "[SILENT]" not in content else "silent"
        }
        result["runs"].append(run_entry)

    if result["runs"]:
        result["last_run_at"] = result["runs"][0]["timestamp"]
        result["last_status"] = result["runs"][0]["status"]
        result["last_summary"] = result["runs"][0]["summary"]
        result["full_output"] = result["runs"][0]["full_output"]

    return result

def build_activity_log(agents_data):
    """Flatten all recent runs into a single chronological activity log."""
    events = []
    for a in agents_data:
        for run in a.get("runs", [])[:3]:
            if run["status"] == "silent":
                continue
            events.append({
                "agent": a["name"],
                "emoji": a["emoji"],
                "color": a["color"],
                "timestamp": run["timestamp"],
                "ts_iso": run["ts_iso"],
                "summary": run["summary"]
            })
    # Sort by ts_iso descending
    events.sort(key=lambda x: x["ts_iso"], reverse=True)
    return events[:20]

def main():
    agents_data = [get_agent_data(a) for a in AGENTS]
    activity = build_activity_log(agents_data)

    runs_today = sum(1 for a in agents_data if a["runs"] and "Jun 16" in a["runs"][0].get("timestamp",""))
    active_count = sum(1 for a in agents_data if a["last_status"] == "ok")
    errors = sum(1 for a in agents_data if a["last_status"] == "error")

    data = {
        "generated": datetime.now().strftime("%b %d, %Y at %I:%M:%S %p"),
        "stats": {
            "total_agents": len(AGENTS),
            "runs_today": runs_today,
            "active": active_count,
            "errors": errors
        },
        "agents": agents_data,
        "activity_log": activity
    }

    OUT_FILE.write_text(json.dumps(data, indent=2))
    print(f"✅ Written {OUT_FILE} — {len(agents_data)} agents, {len(activity)} activity events")

if __name__ == "__main__":
    main()
