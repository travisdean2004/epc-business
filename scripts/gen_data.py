#!/usr/bin/env python3
"""Reads cron output files and writes /tmp/data.json for the dashboard."""
import os, json, re
from datetime import datetime, timezone

BASE = os.path.expanduser("~/.hermes/cron/output")
JOBS_FILE = "/Users/tdizzlewizzle/.hermes/cron/jobs.json"

with open(JOBS_FILE) as f:
    raw = json.load(f)
jobs_list = raw.get("jobs", [])
jobs_meta = {j["id"]: j for j in jobs_list}

results = []

for job_id, meta in jobs_meta.items():
    job_dir = os.path.join(BASE, job_id)
    last_output = ""
    
    if os.path.isdir(job_dir):
        files = sorted(os.listdir(job_dir), reverse=True)
        if files:
            fpath = os.path.join(job_dir, files[0])
            try:
                with open(fpath) as f:
                    content = f.read()
                m = re.search(r'## Response\s*\n(.*)', content, re.DOTALL)
                if m:
                    last_output = m.group(1).strip()[:3000]
                else:
                    last_output = content[-3000:].strip()
            except Exception as e:
                last_output = f"(error reading: {e})"

    results.append({
        "job_id": job_id,
        "name": meta.get("name", job_id),
        "schedule": meta.get("schedule_display") or meta.get("schedule", ""),
        "last_run_at": meta.get("last_run_at") or "",
        "last_status": meta.get("last_status") or "",
        "next_run_at": meta.get("next_run_at") or "",
        "enabled": meta.get("enabled", True),
        "paused": bool(meta.get("paused_at")),
        "last_output": last_output,
        "has_output": bool(last_output),
    })

results.sort(key=lambda x: x["last_run_at"] or "", reverse=True)

out = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "agent_count": len(results),
    "agents": results
}

with open("/tmp/data.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"OK: {len(results)} agents")
for a in results:
    print(f"  {a['name'][:40]:40} | last: {a['last_run_at'][:16] if a['last_run_at'] else 'never':16} | output: {len(a['last_output'])} chars")
