#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SQLite job store — cross-run dedup, sightings, clusters, application tracking."""

import re
import json
import uuid
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from modules.sb_utils import NOT_AVAILABLE, PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "artifacts" / "jobs.db"
DEFAULT_JSON_DIR = PROJECT_ROOT / "artifacts" / "json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY,
    name_norm       TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posting_clusters (
    id              INTEGER PRIMARY KEY,
    board           TEXT NOT NULL,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    title_norm      TEXT,
    location_norm   TEXT,
    fingerprint     TEXT NOT NULL,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    listing_count   INTEGER DEFAULT 1,
    ghost_score     REAL DEFAULT 0,
    flags_json      TEXT DEFAULT '[]',
    UNIQUE(board, fingerprint)
);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY,
    board           TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    cluster_id      INTEGER NOT NULL REFERENCES posting_clusters(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    url             TEXT,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    salary          TEXT,
    snippet         TEXT,
    posted          TEXT,
    sponsored       INTEGER DEFAULT 0,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    seen_count      INTEGER DEFAULT 1,
    UNIQUE(board, external_id)
);

CREATE TABLE IF NOT EXISTS sightings (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),
    scraped_at      TEXT NOT NULL,
    search_query    TEXT,
    search_location TEXT,
    page_number     INTEGER,
    run_id          TEXT,
    json_source     TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY,
    cluster_id      INTEGER NOT NULL REFERENCES posting_clusters(id),
    job_id          INTEGER REFERENCES jobs(id),
    status          TEXT NOT NULL DEFAULT 'applied',
    applied_at      TEXT,
    notes           TEXT,
    updated_at      TEXT NOT NULL,
    UNIQUE(cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_board_external ON jobs(board, external_id);
CREATE INDEX IF NOT EXISTS idx_jobs_cluster ON jobs(cluster_id);
CREATE INDEX IF NOT EXISTS idx_sightings_job ON sightings(job_id);
CREATE INDEX IF NOT EXISTS idx_sightings_run ON sightings(run_id);
CREATE INDEX IF NOT EXISTS idx_clusters_company ON posting_clusters(company_id);
"""


def default_db_path():
    return DEFAULT_DB_PATH


def _now_iso():
    return datetime.now().isoformat()


def normalize_company(name):
    if not name or name == NOT_AVAILABLE:
        return ""
    text = name.lower().strip()
    text = re.sub(r"\b(inc|llc|ltd|corp|corporation|co)\b\.?", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title):
    if not title or title == NOT_AVAILABLE:
        return ""
    text = title.lower().strip()
    for token in ("remote", "hybrid", "onsite", "full-time", "part-time", "contract"):
        text = text.replace(token, " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_location(location):
    if not location or location == NOT_AVAILABLE:
        return ""
    text = location.lower().strip()
    if "remote" in text:
        return "remote"
    return re.sub(r"\s+", " ", text)


def cluster_fingerprint(board, company_norm, title_norm, location_norm=""):
    raw = f"{board}|{company_norm}|{title_norm}|{location_norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def external_id_for_job(job, board="indeed"):
    for field in ("job_key", "job_id"):
        value = job.get(field)
        if value and value != NOT_AVAILABLE:
            return str(value)
    url = job.get("url")
    if url and url != NOT_AVAILABLE:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    title = normalize_title(job.get("title", ""))
    company = normalize_company(job.get("company", ""))
    if title and company:
        return hashlib.sha256(f"{company}|{title}".encode("utf-8")).hexdigest()[:16]
    return None


def posted_for_job(job):
    """Return Indeed posting age text from common scrape field names."""
    if not job:
        return None
    empty = {NOT_AVAILABLE, "N/A", "—", ""}
    for key in ("posted", "posted_date", "date_posted"):
        value = job.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in empty:
            return text.split("\n")[0].strip()
    return None


def job_location_for_db(job):
    """Normalize location from board-specific scrape field names."""
    if not job:
        return ""
    for key in ("location", "job_location"):
        value = job.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in (NOT_AVAILABLE, "N/A", "—"):
            return text
    return ""


def detect_board_from_json(path, data=None):
    """Infer job board from filename, metadata, or job URLs."""
    path = Path(path)
    if data is None:
        data = json.loads(path.read_text(encoding="utf-8"))

    name = path.name.lower()
    if name.startswith("dice_data_"):
        return "dice"
    if name.startswith("glassdoor_data_"):
        return "glassdoor"

    meta = data.get("metadata") or {}
    board_hint = str(meta.get("board") or meta.get("source") or "").lower()
    if "dice" in board_hint:
        return "dice"
    if "glassdoor" in board_hint:
        return "glassdoor"
    if board_hint in ("indeed", "indeed.com"):
        return "indeed"

    for job in data.get("jobs") or []:
        url = (job.get("url") or "").lower()
        if "dice.com" in url:
            return "dice"
        if "glassdoor.com" in url:
            return "glassdoor"
        if "indeed.com" in url:
            return "indeed"

    return "indeed"


@contextmanager
def connect(db_path=None):
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _upsert_company(conn, company_name, seen_at):
    name_norm = normalize_company(company_name)
    if not name_norm:
        name_norm = "unknown"
    row = conn.execute(
        "SELECT id FROM companies WHERE name_norm = ?", (name_norm,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE companies SET display_name = ?, last_seen_at = ? WHERE id = ?",
            (company_name or name_norm, seen_at, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        """
        INSERT INTO companies (name_norm, display_name, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        (name_norm, company_name or name_norm, seen_at, seen_at),
    )
    return cur.lastrowid


def _upsert_cluster(conn, board, company_id, job, seen_at):
    title_norm = normalize_title(job.get("title"))
    location_norm = normalize_location(job_location_for_db(job))
    fp = cluster_fingerprint(board, normalize_company(job.get("company")), title_norm, location_norm)
    row = conn.execute(
        "SELECT id, listing_count, first_seen_at FROM posting_clusters WHERE board = ? AND fingerprint = ?",
        (board, fp),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE posting_clusters
            SET last_seen_at = ?, listing_count = listing_count + 1,
                title_norm = COALESCE(?, title_norm),
                location_norm = COALESCE(?, location_norm)
            WHERE id = ?
            """,
            (seen_at, title_norm or None, location_norm or None, row["id"]),
        )
        return row["id"], False
    cur = conn.execute(
        """
        INSERT INTO posting_clusters
            (board, company_id, title_norm, location_norm, fingerprint,
             first_seen_at, last_seen_at, listing_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (board, company_id, title_norm, location_norm, fp, seen_at, seen_at),
    )
    return cur.lastrowid, True


def _score_cluster(conn, cluster_id):
    rows = conn.execute("SELECT external_id, first_seen_at, last_seen_at, seen_count FROM jobs WHERE cluster_id = ?",(cluster_id,),).fetchall()
    if not rows:
        return 0, []

    flags = []
    score = 0.0
    distinct_ids = len({r["external_id"] for r in rows})
    total_seen = sum(r["seen_count"] for r in rows)

    if distinct_ids >= 2:
        flags.append("repost")
        score += 1.0
    if total_seen >= 4:
        flags.append("high_frequency")
        score += 1.5
    if distinct_ids >= 3 and total_seen >= 5:
        flags.append("ghost_candidate")
        score += 2.0

    conn.execute("UPDATE posting_clusters SET ghost_score = ?, flags_json = ? WHERE id = ?",(score, json.dumps(flags), cluster_id),)
    return score, flags


def upsert_jobs(jobs, board="indeed", run_id=None, json_source=None, db_path=None):
    """Insert or update jobs; record sightings. Returns summary stats."""
    if not jobs:
        return {"new": 0, "updated": 0, "sightings": 0}

    init_db(db_path)
    run_id = run_id or str(uuid.uuid4())
    stats = {"new": 0, "updated": 0, "sightings": 0, "run_id": run_id}

    with connect(db_path) as conn:
        for job in jobs:
            ext_id = external_id_for_job(job, board)
            if not ext_id:
                continue

            seen_at = job.get("scraped_at") or _now_iso()
            company_id = _upsert_company(conn, job.get("company"), seen_at)
            cluster_id, _ = _upsert_cluster(conn, board, company_id, job, seen_at)
            existing = conn.execute("SELECT id, seen_count FROM jobs WHERE board = ? AND external_id = ?", (board, ext_id),).fetchone()

            sponsored = 1 if job.get("sponsored") else 0
            location = job_location_for_db(job)
            if existing:
                conn.execute(
                    """
                    UPDATE jobs SET
                        cluster_id = ?, company_id = ?, url = ?, title = ?, company = ?,
                        location = ?, salary = ?, snippet = ?, posted = ?, sponsored = ?,
                        last_seen_at = ?, seen_count = seen_count + 1
                    WHERE id = ?
                    """,
                    (
                        cluster_id,
                        company_id,
                        job.get("url"),
                        job.get("title"),
                        job.get("company"),
                        location,
                        job.get("salary"),
                        job.get("snippet"),
                        posted_for_job(job),
                        sponsored,
                        seen_at,
                        existing["id"],
                    ),
                )
                job_id = existing["id"]
                stats["updated"] += 1
            else:
                cur = conn.execute(
                    """
                    INSERT INTO jobs
                        (board, external_id, cluster_id, company_id, url, title, company,
                         location, salary, snippet, posted, sponsored,
                         first_seen_at, last_seen_at, seen_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        board,
                        ext_id,
                        cluster_id,
                        company_id,
                        job.get("url"),
                        job.get("title"),
                        job.get("company"),
                        location,
                        job.get("salary"),
                        job.get("snippet"),
                        posted_for_job(job),
                        sponsored,
                        seen_at,
                        seen_at,
                    ),
                )
                job_id = cur.lastrowid
                stats["new"] += 1

            conn.execute(
                """
                INSERT INTO sightings
                    (job_id, scraped_at, search_query, search_location, page_number, run_id, json_source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    seen_at,
                    job.get("search_query") or job.get("query"),
                    job.get("search_location") or job.get("location"),
                    job.get("page_number") or job.get("page"),
                    run_id,
                    json_source,
                ),
            )
            stats["sightings"] += 1
            _score_cluster(conn, cluster_id)

    return stats


def import_json_file(path, board="indeed", db_path=None):
    path = Path(path)
    init_db(db_path)
    with connect(db_path) as conn:
        already = conn.execute("SELECT 1 FROM sightings WHERE json_source = ? LIMIT 1", (path.name,),).fetchone()
        if already:
            return {"skipped": True, "new": 0, "updated": 0, "sightings": 0}

    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    if board == "indeed":
        board = detect_board_from_json(path, data)
    return upsert_jobs(jobs, board=board, json_source=str(path.name), db_path=db_path)


def import_all_json(json_dir=None, db_path=None):
    json_dir = Path(json_dir) if json_dir else DEFAULT_JSON_DIR
    totals = {"files": 0, "skipped": 0, "new": 0, "updated": 0, "sightings": 0}
    if not json_dir.exists():
        return totals

    for path in sorted(json_dir.glob("*.json")):
        if path.name.startswith("combined_"):
            continue
        board = detect_board_from_json(path)
        stats = import_json_file(path, board=board, db_path=db_path)
        totals["files"] += 1
        if stats.get("skipped"):
            totals["skipped"] += 1
            continue
        totals["new"] += stats.get("new", 0)
        totals["updated"] += stats.get("updated", 0)
        totals["sightings"] += stats.get("sightings", 0)
    return totals


def load_json_artifacts(json_dir=None):
    """Load all JSON scrape files for reporting (excluding combined_*)."""
    json_dir = Path(json_dir) if json_dir else DEFAULT_JSON_DIR
    artifacts = []
    if not json_dir.exists():
        return artifacts

    for path in sorted(json_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.startswith("combined_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        meta = data.get("metadata") or {}
        board = detect_board_from_json(path, data)
        artifacts.append(
            {
                "filename": path.name,
                "path": str(path),
                "board": board,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "total_jobs": meta.get("total_jobs", len(data.get("jobs") or [])),
                "scraped_at": meta.get("scraped_at"),
                "scraped_at_readable": meta.get("scraped_at_readable"),
                "query": (meta.get("search_params") or {}).get("query"),
                "location": (meta.get("search_params") or {}).get("location"),
                "jobs": data.get("jobs") or [],
            }
        )
    return artifacts


def get_db_summary(db_path=None):
    db_path = Path(db_path) if db_path else default_db_path()
    if not db_path.exists():
        return {"exists": False, "path": str(db_path)}

    init_db(db_path)
    with connect(db_path) as conn:
        jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        companies = conn.execute("SELECT COUNT(*) AS c FROM companies").fetchone()["c"]
        clusters = conn.execute("SELECT COUNT(*) AS c FROM posting_clusters").fetchone()["c"]
        sightings = conn.execute("SELECT COUNT(*) AS c FROM sightings").fetchone()["c"]
        applications = conn.execute("SELECT COUNT(*) AS c FROM applications").fetchone()["c"]
        ghost = conn.execute("SELECT COUNT(*) AS c FROM posting_clusters WHERE ghost_score >= 2").fetchone()["c"]
        repost = conn.execute("SELECT COUNT(*) AS c FROM posting_clusters WHERE flags_json LIKE '%repost%'").fetchone()["c"]

    return {
        "exists": True,
        "path": str(db_path),
        "jobs": jobs,
        "companies": companies,
        "clusters": clusters,
        "sightings": sightings,
        "applications": applications,
        "ghost_candidates": ghost,
        "repost_clusters": repost,
    }


def get_db_jobs(limit=None, db_path=None):
    init_db(db_path)
    limit_clause = ""
    params = ()
    if limit is not None:
        limit_clause = "LIMIT ?"
        params = (int(limit),)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT j.*, c.display_name AS company_display,
                   pc.ghost_score, pc.flags_json, pc.listing_count AS cluster_listings,
                   a.status AS application_status, a.applied_at,
                   (SELECT s.search_query FROM sightings s
                    WHERE s.job_id = j.id ORDER BY s.scraped_at DESC LIMIT 1) AS search_query,
                   (SELECT s.scraped_at FROM sightings s
                    WHERE s.job_id = j.id ORDER BY s.scraped_at DESC LIMIT 1) AS latest_scraped_at
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            JOIN posting_clusters pc ON pc.id = j.cluster_id
            LEFT JOIN applications a ON a.cluster_id = j.cluster_id
            ORDER BY j.last_seen_at DESC
            {limit_clause}
            """,
            params,
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["flags"] = json.loads(item.pop("flags_json") or "[]")
        except json.JSONDecodeError:
            item["flags"] = []
        result.append(item)
    return result


_JOBS_FROM = """
    FROM jobs j
    JOIN companies c ON c.id = j.company_id
    JOIN posting_clusters pc ON pc.id = j.cluster_id
    LEFT JOIN applications a ON a.cluster_id = j.cluster_id
"""

_JOBS_SELECT = """
    SELECT j.*, c.display_name AS company_display,
           pc.ghost_score, pc.flags_json, pc.listing_count AS cluster_listings,
           a.status AS application_status, a.applied_at,
           (SELECT s.search_query FROM sightings s
            WHERE s.job_id = j.id ORDER BY s.scraped_at DESC LIMIT 1) AS search_query,
           (SELECT s.scraped_at FROM sightings s
            WHERE s.job_id = j.id ORDER BY s.scraped_at DESC LIMIT 1) AS latest_scraped_at
"""


def _job_row_dict(row):
    item = dict(row)
    try:
        item["flags"] = json.loads(item.pop("flags_json") or "[]")
    except json.JSONDecodeError:
        item["flags"] = []
    return item


def _jobs_filter_clause(q=None, field="both", board=None, status="all"):
    conditions = []
    params = []
    if q:
        pattern = f"%{q.strip()}%"
        field = (field or "both").lower()
        if field == "company":
            conditions.append("LOWER(c.display_name) LIKE LOWER(?)")
            params.append(pattern)
        elif field == "title":
            conditions.append("LOWER(j.title) LIKE LOWER(?)")
            params.append(pattern)
        else:
            conditions.append("(LOWER(c.display_name) LIKE LOWER(?) OR LOWER(j.title) LIKE LOWER(?))")
            params.extend([pattern, pattern])
    if board and board.lower() != "all":
        conditions.append("LOWER(j.board) = ?")
        params.append(board.lower())
    status = (status or "all").lower()
    if status == "open":
        conditions.append("(a.status IS NULL OR a.status = '' OR a.status = 'none')")
    elif status == "applied":
        conditions.append("a.status = 'applied'")
    elif status == "skipped":
        conditions.append("a.status IN ('skipped', 'rejected')")
    elif status == "interview":
        conditions.append("a.status = 'interviewing'")
    elif status == "offer":
        conditions.append("a.status = 'offer'")
    elif status == "ghost":
        conditions.append("pc.flags_json LIKE '%ghost_candidate%'")
    where = " AND ".join(conditions) if conditions else "1=1"
    return where, params


def search_db_jobs(q=None,field="both",board=None,status="all",limit=50,offset=0,db_path=None,):
    """Query jobs with optional text search, board, and application-status filters."""

    init_db(db_path)
    where, params = _jobs_filter_clause(q, field, board, status)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c {_JOBS_FROM} WHERE {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"""
            {_JOBS_SELECT}
            {_JOBS_FROM}
            WHERE {where}
            ORDER BY j.last_seen_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    return [_job_row_dict(row) for row in rows], int(total)


def get_db_board_counts(db_path=None):
    init_db(db_path)
    counts = {"indeed": 0, "dice": 0, "glassdoor": 0}
    with connect(db_path) as conn:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
            return counts
        rows = conn.execute("SELECT board, COUNT(*) AS c FROM jobs GROUP BY board").fetchall()
    for row in rows:
        board = (row["board"] or "").lower()
        if board in counts:
            counts[board] = row["c"]
    return counts


def load_json_artifact(filename, json_dir=None):
    """Load a single scrape JSON artifact by filename."""
    json_dir = Path(json_dir) if json_dir else DEFAULT_JSON_DIR
    path = json_dir / Path(filename).name
    if not path.exists() or path.name.startswith("combined_"):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    meta = data.get("metadata") or {}
    board = detect_board_from_json(path, data)
    return {
        "filename": path.name,
        "path": str(path),
        "board": board,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "total_jobs": meta.get("total_jobs", len(data.get("jobs") or [])),
        "scraped_at": meta.get("scraped_at"),
        "scraped_at_readable": meta.get("scraped_at_readable"),
        "query": (meta.get("search_params") or {}).get("query"),
        "location": (meta.get("search_params") or {}).get("location"),
        "jobs": data.get("jobs") or [],
    }


def get_db_by_external_ids(board, external_ids, db_path=None):
    """Lookup DB jobs for a board + list of external ids (for JSON scrape panels)."""
    board = (board or "indeed").lower()
    ext_list = [str(e) for e in external_ids if e]
    if not ext_list:
        return {}
    init_db(db_path)
    placeholders = ",".join("?" * len(ext_list))
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            {_JOBS_SELECT}
            {_JOBS_FROM}
            WHERE LOWER(j.board) = ? AND j.external_id IN ({placeholders})
            """,
            [board, *ext_list],
        ).fetchall()
    result = {}
    for row in rows:
        job = _job_row_dict(row)
        result[(board, job["external_id"])] = job
    return result


def get_ghost_clusters(limit=30, db_path=None):
    """Return posting clusters flagged as ghost candidates (ghost_score >= 2)."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT pc.id, pc.ghost_score, pc.flags_json, pc.title_norm, pc.location_norm,
                   pc.listing_count, pc.first_seen_at, pc.last_seen_at,
                   c.display_name AS company, c.name_norm AS company_norm,
                   COUNT(j.id) AS job_count,
                   COALESCE(SUM(j.seen_count), 0) AS total_seen
            FROM posting_clusters pc
            JOIN companies c ON c.id = pc.company_id
            LEFT JOIN jobs j ON j.cluster_id = pc.id
            WHERE pc.ghost_score >= 2
            GROUP BY pc.id
            ORDER BY pc.ghost_score DESC, total_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["flags"] = json.loads(item.pop("flags_json") or "[]")
        except json.JSONDecodeError:
            item["flags"] = []
        result.append(item)
    return result


def get_db_companies(limit=None, db_path=None):
    init_db(db_path)
    limit_clause = ""
    params = ()
    if limit is not None:
        limit_clause = "LIMIT ?"
        params = (int(limit),)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT c.display_name, c.name_norm, c.first_seen_at, c.last_seen_at,
                   COUNT(j.id) AS job_count,
                   MAX(pc.ghost_score) AS max_ghost_score
            FROM companies c
            LEFT JOIN jobs j ON j.company_id = c.id
            LEFT JOIN posting_clusters pc ON pc.company_id = c.id
            GROUP BY c.id
            HAVING job_count > 0
            ORDER BY job_count DESC, c.last_seen_at DESC
            {limit_clause}
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


APPLICATION_STATUSES = ("applied", "skipped", "interviewing", "rejected", "offer")


def set_application_for_job(job_row_id, status, notes=None, db_path=None):
    """Record application status for a job (by jobs.id)."""
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT id, cluster_id FROM jobs WHERE id = ?",(int(job_row_id),),).fetchone()
        if not row:
            return False

        now = _now_iso()
        applied_at = now if status == "applied" else None
        conn.execute(
            """
            INSERT INTO applications (cluster_id, job_id, status, applied_at, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cluster_id) DO UPDATE SET
                job_id = excluded.job_id,
                status = excluded.status,
                applied_at = COALESCE(excluded.applied_at, applications.applied_at),
                notes = COALESCE(excluded.notes, applications.notes),
                updated_at = excluded.updated_at
            """,
            (row["cluster_id"], row["id"], status, applied_at, notes, now),
        )
    return True


def set_application_by_external_id(board, external_id, status, notes=None, db_path=None):
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM jobs WHERE board = ? AND external_id = ?", (board, external_id),).fetchone()
    if not row:
        return False
    return set_application_for_job(row["id"], status, notes=notes, db_path=db_path)


def clear_application_for_job(job_row_id, db_path=None):
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT cluster_id FROM jobs WHERE id = ?", (int(job_row_id),),).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM applications WHERE cluster_id = ?", (row["cluster_id"],))
    return True
