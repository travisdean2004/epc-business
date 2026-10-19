#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""FastAPI routes for interactive job reports."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from modules.job_report_html import (HTML_DIR, SCREENSHOTS_DIR, get_ghost_slugs_for_reports, render_db_jobs_table_html, render_json_scrape_table_html,)
from modules.job_store import (APPLICATION_STATUSES, clear_application_for_job, default_db_path, load_json_artifact, search_db_jobs, set_application_by_external_id, set_application_for_job,)

app = FastAPI(title="Indeed Job Reports", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type"],)

class StatusPayload(BaseModel):
    status: str
    notes: str | None = None

# ___ health check endpoint:
@app.get("/api/health")
def health():
    return {"ok": True, "service": "indeed-job-reports"}


@app.get("/api/jobs")
def list_jobs(
    q: str | None = None,
    field: str = Query("both", pattern="^(company|title|both)$"),
    board: str | None = None,
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: str | None = None,):

    db_path = db or str(default_db_path())
    jobs, total = search_db_jobs(q=q, field=field, board=board, status=status, limit=limit, offset=offset, db_path=db_path,)
    ghost_slugs = get_ghost_slugs_for_reports(db_path=db_path)
    rows_html = render_db_jobs_table_html(jobs, ghost_slugs=ghost_slugs, company_link_target="jobs")
    if not rows_html and total == 0:
        rows_html = '<tr><td colspan="12" class="empty">No jobs match your query.</td></tr>'
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "q": q or "",
        "field": field,
        "board": board or "all",
        "status": status,
        "rows_html": rows_html,
    }

# ___ scrape jobs endpoint:
@app.get("/api/scrapes/{filename}/jobs")
def scrape_jobs(
    filename: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    json_dir: str | None = None,
    db: str | None = None,):
    
    safe_name = Path(filename).name
    if safe_name != filename or safe_name.startswith("combined_"):
        raise HTTPException(status_code=400, detail="invalid filename")

    artifact = load_json_artifact(safe_name, json_dir=json_dir)
    if not artifact:
        raise HTTPException(status_code=404, detail="scrape file not found")

    db_path = db or str(default_db_path())
    ghost_slugs = get_ghost_slugs_for_reports(db_path=db_path)
    table_html = render_json_scrape_table_html(artifact, ghost_slugs=ghost_slugs, limit=limit, offset=offset, db_path=db_path,)
    jobs = artifact.get("jobs") or []
    total = len(jobs)
    return {
        "filename": safe_name,
        "total": total,
        "limit": limit,
        "offset": offset,
        "table_html": table_html,
    }


@app.post("/api/jobs/{job_id}/status")
def set_job_status(job_id: int, payload: StatusPayload, db: str | None = None):
    status = payload.status.strip().lower()
    if status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {APPLICATION_STATUSES}")
    ok = set_application_for_job(job_id, status, notes=payload.notes, db_path=db or str(default_db_path()))
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "status": status}

# ___ clear job status endpoint:
@app.delete("/api/jobs/{job_id}/status")
def clear_job_status(job_id: int, db: str | None = None):
    ok = clear_application_for_job(job_id, db_path=db or str(default_db_path()))
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": ok}

# ___ set external job status endpoint:
@app.post("/api/jobs/by-external/{board}/{external_id}/status")
def set_external_status(board: str, external_id: str, payload: StatusPayload, db: str | None = None):
    status = payload.status.strip().lower()
    if status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {APPLICATION_STATUSES}")
    ok = set_application_by_external_id(board, external_id, status, notes=payload.notes, db_path=db or str(default_db_path()),)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "status": status}

# ___ serve screenshot endpoint:
@app.get("/screenshots/{file_path:path}")
def serve_screenshot(file_path: str):
    rel = Path(file_path)
    if ".." in rel.parts:
        raise HTTPException(status_code=403, detail="forbidden")
    path = SCREENSHOTS_DIR / rel
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)

# ___ mount static files endpoint:
def mount_static(app_instance: FastAPI):
    if HTML_DIR.is_dir():
        app_instance.mount("/", StaticFiles(directory=str(HTML_DIR), html=True), name="html")
