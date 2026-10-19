#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Generate HTML report variants from JSON artifacts and SQLite job store."""

import re
import html
import json
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import quote_plus
from modules.sb_utils import PROJECT_ROOT
from modules.job_store import (default_db_path, get_db_companies, get_db_board_counts, get_db_jobs, get_db_summary, get_ghost_clusters, load_json_artifacts, normalize_company,)

HTML_DIR = PROJECT_ROOT / "artifacts" / "html"
SCREENSHOTS_DIR = PROJECT_ROOT / "artifacts" / "screenshots"
VARIANTS = ("dashboard", "table", "search", "cards", "compare", "companies", "screenshots", "index")
_NOT_AVAILABLE = "Not Available"


def _esc(value):
    if value is None:
        return ""
    return html.escape(str(value))


def _badge(text, kind="neutral"):
    colors = {
        "new": ("#6ee7b7", "#064e3b"),
        "known": ("#93c5fd", "#1e3a8a"),
        "repost": ("#fcd34d", "#78350f"),
        "ghost": ("#fca5a5", "#7f1d1d"),
        "applied": ("#c4b5fd", "#4c1d95"),
        "user-applied": ("#6ee7b7", "#064e3b"),
        "neutral": ("#cbd5e1", "#334155"),
    }
    fg, bg = colors.get(kind, colors["neutral"])
    return (f'<span class="badge" style="color:{fg};background:{bg}">{_esc(text)}</span>')


def _db_badge(text, kind="neutral"):
    colors = {
        "new": ("#6ee7b7", "#064e3b"),
        "known": ("#93c5fd", "#1e3a8a"),
        "neutral": ("#cbd5e1", "#334155"),
    }
    fg, bg = colors.get(kind, colors["neutral"])
    return (f'<span class="badge badge-db" style="color:{fg};background:{bg}">{_esc(text)}</span>')


def _company_slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "unknown").lower()).strip("-") or "unknown"


def _build_ghost_company_slugs(ghost_clusters=None, db_jobs=None):
    slugs = set()
    for cluster in ghost_clusters or []:
        name = cluster.get("company")
        if name:
            slugs.add(_company_slug(name))
    for job in db_jobs or []:
        if "ghost_candidate" in (job.get("flags") or []):
            name = job.get("company_display") or job.get("company")
            if name:
                slugs.add(_company_slug(name))
    return frozenset(slugs)


def get_ghost_slugs_for_reports(db_path=None):
    clusters = get_ghost_clusters(limit=500, db_path=db_path)
    return _build_ghost_company_slugs(clusters, db_jobs=[])


def render_db_jobs_table_html(jobs, ghost_slugs=None, company_link_target="jobs"):
    rows = ""
    for job in jobs or []:
        rows += _render_job_table_row(
            job,
            show_status=True,
            show_board=True,
            show_seen=True,
            actions_html=_job_actions_html(job, compact=True),
            company_link_target=company_link_target,
            ghost_company_slugs=ghost_slugs,
        )
    return rows


def render_json_scrape_table_html(artifact, ghost_slugs=None, limit=200, offset=0, db_path=None):
    from modules.job_store import get_db_by_external_ids

    all_jobs = artifact.get("jobs") or []
    total = len(all_jobs)
    jobs = all_jobs[offset : offset + limit]
    if not jobs:
        return '<div class="empty">No jobs in file</div>'

    board = artifact.get("board", "indeed")
    ext_ids = [j.get("job_key") or j.get("job_id") or "" for j in jobs]
    db_by_external = get_db_by_external_ids(board, ext_ids, db_path=db_path)
    job_rows = _json_job_rows(jobs, db_by_external, ghost_slugs, board)
    note = ""
    if total > len(jobs):
        note = f'<p class="meta">Showing {offset + 1}–{offset + len(jobs)} of {total} jobs in file.</p>'
    return f"""{note}<div class="table-scroll">
      <table class="inner-table sortable-table actions-table">
        <thead>{_job_table_head(include_db=True, include_key=True, include_board=True)}</thead>
        <tbody>{job_rows or '<tr><td colspan="11" class="empty">No jobs in file</td></tr>'}</tbody>
      </table>
    </div>"""


def _company_is_ghost(name, flags=None, ghost_slugs=None):
    if ghost_slugs and _company_slug(name) in ghost_slugs:
        return True
    if flags and "ghost_candidate" in flags:
        return True
    return False


def _company_name_html(name, link=False, link_target="companies", is_ghost=False):
    label = name or "Unknown"
    inner = _esc(label)
    ghost_cls = " company-ghost" if is_ghost else ""
    if not link:
        return f'<span class="company-name{ghost_cls}">{inner}</span>'
    slug = _company_slug(label)
    if link_target == "jobs":
        return (
            f'<a class="company-name co-link co-link-sqlite{ghost_cls}" '
            f'href="report_table.html#company-{_esc(slug)}">{inner}</a>'
        )
    return (
        f'<a class="company-name co-link co-link-json{ghost_cls}" '
        f'href="report_companies.html#{_esc(slug)}">{inner}</a>'
    )


BOARD_LABELS = {
    "indeed": "Indeed",
    "dice": "Dice",
    "glassdoor": "Glassdoor",
}

BOARD_BADGE_STYLES = {
    "indeed": ("#93c5fd", "#1e3a8a"),
    "dice": ("#fcd34d", "#78350f"),
    "glassdoor": ("#6ee7b7", "#064e3b"),
}


def _board_label(board):
    key = (board or "indeed").lower()
    return BOARD_LABELS.get(key, key.title() or "Indeed")


def _board_badge(board):
    key = (board or "indeed").lower()
    fg, bg = BOARD_BADGE_STYLES.get(key, ("#cbd5e1", "#334155"))
    return (
        f'<span class="badge badge-board badge-board-{_esc(key)}" '
        f'style="color:{fg};background:{bg}">{_esc(_board_label(key))}</span>'
    )


def _open_board_label(board):
    return f"Open {_board_label(board)}"


def _clean_field(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text in (_NOT_AVAILABLE, "—"):
        return ""
    return text


def _salary_sort_num(salary):
    text = _clean_field(salary)
    if not text:
        return 0
    nums = re.findall(r"\d+", text.replace(",", ""))
    return int(nums[0]) if nums else 0


def _date_sort_val(value):
    text = _clean_field(value)
    if not text:
        return ""
    return text[:19] if "T" in text else text


def _posted_sort_rank(posted):
    text = (_clean_field(posted) or "").lower()
    if not text:
        return 999999
    if "just posted" in text or "today" in text or "hour" in text or "minute" in text:
        return 0
    match = re.search(r"(\d+)", text)
    amount = int(match.group(1)) if match else 1
    if "day" in text:
        return amount
    if "week" in text:
        return amount * 7
    if "month" in text:
        return amount * 30
    return 500000


def _posted_display(posted):
    text = _clean_field(posted)
    return text if text else "—"


def _job_posted_raw(job, db_job=None):
    merged = {**(job or {}), **(db_job or {})}
    for key in ("posted", "posted_date", "date_posted"):
        val = _clean_field(merged.get(key))
        if val:
            return val
    return ""


def _scraped_display(job, db_job=None):
    merged = {**(job or {}), **(db_job or {})}
    raw = (
        merged.get("scraped_at")
        or merged.get("latest_scraped_at")
        or merged.get("last_seen_at")
        or merged.get("first_seen_at")
        or ""
    )
    sort_val = _date_sort_val(raw)
    if not sort_val:
        return "—", ""
    display = sort_val[:10] if "T" in sort_val else sort_val[:16]
    return display, sort_val


def _job_sort_attrs(job, db_job=None):
    merged = {**(job or {}), **(db_job or {})}
    company = merged.get("company_display") or merged.get("company") or ""
    title = merged.get("title") or ""
    position = merged.get("search_query") or merged.get("query") or ""
    salary_num = _salary_sort_num(merged.get("salary"))
    _, scraped = _scraped_display(job, db_job)
    posted = _job_posted_raw(job, db_job)
    posted_rank = _posted_sort_rank(posted)
    seen = merged.get("seen_count", 1) or 1
    flags = merged.get("flags") or []
    flags_csv = ",".join(flags)
    board = (merged.get("board") or "indeed").lower()
    return (
        f'data-company="{_esc(company.lower())}" '
        f'data-board="{_esc(board)}" '
        f'data-position="{_esc(position.lower())}" '
        f'data-title="{_esc(title.lower())}" '
        f'data-salary="{salary_num}" '
        f'data-scraped="{_esc(scraped)}" '
        f'data-posted-rank="{posted_rank}" '
        f'data-seen="{seen}" '
        f'data-flags="{_esc(flags_csv)}"'
    )


def _th_sort(label, key, sort_type="text", extra_class=""):
    classes = " ".join(part for part in ("sortable", extra_class) if part)
    return (
        f'<th class="{classes}" data-sort="{key}" data-sort-type="{sort_type}">'
        f'{label}<span class="sort-ind"></span></th>'
    )


def _job_table_head(*, include_db=False, include_status=False, include_board=False, include_seen=False, include_key=False,):
    parts = []
    if include_db:
        parts.append('<th class="col-db">DB</th>')
    if include_status:
        parts.append('<th class="col-status">Status</th>')
    if include_board:
        parts.append('<th class="col-board">Source</th>')
    parts.extend(
        [
            _th_sort("Company", "company", extra_class="col-company"),
            _th_sort("Position", "position", extra_class="col-position"),
            _th_sort("Title", "title", extra_class="col-title"),
            '<th class="col-loc">Location</th>',
            _th_sort("Salary", "salary", "num", "col-salary"),
            _th_sort("Posted", "postedRank", "num", "col-posted"),
            _th_sort("Scraped", "scraped", "date", "col-scraped"),
        ]
    )
    if include_seen:
        parts.append(_th_sort("Seen", "seen", "num"))
    if include_key:
        parts.append('<th class="col-key">Job key</th>')
    parts.append('<th class="col-actions">Actions</th>')
    return "<tr>" + "".join(parts) + "</tr>"


def _render_job_table_row(
  job, db_job=None, *, show_db=False, show_status=False, 
  show_board=False, show_seen=False, show_key=False, actions_html="", 
  company_link_target="companies", ghost_company_slugs=None, board=None,):

    action_job = {**(job or {}), **(db_job or {})} if db_job else dict(job or {})
    app_st = action_job.get("application_status") or "none"
    row_board = (board or action_job.get("board") or job.get("board") or "indeed").lower()
    company = job.get("company") or action_job.get("company_display") or action_job.get("company") or ""
    flags = action_job.get("flags") or []
    is_ghost = _company_is_ghost(company, flags=flags, ghost_slugs=ghost_company_slugs)
    company_slug = _company_slug(company)
    position = _clean_field(job.get("search_query")) or _clean_field(action_job.get("search_query")) or "—"
    title = job.get("title") or action_job.get("title") or ""
    location = (
        job.get("location")
        or job.get("job_location")
        or action_job.get("location")
        or ""
    )
    salary = job.get("salary") or action_job.get("salary") or ""
    posted = _posted_display(_job_posted_raw(job, db_job))
    scraped_display, _ = _scraped_display(job, db_job)
    attrs = _job_sort_attrs(job, db_job)

    cells = []
    if show_db:
        ext = job.get("job_key") or job.get("job_id") or ""
        if db_job:
            cells.append(f'<td class="col-db">{_db_badge("in DB", "known")}</td>')
        elif ext:
            cells.append(f'<td class="col-db">{_db_badge("not in DB", "new")}</td>')
        else:
            cells.append('<td class="col-db"></td>')
    if show_status:
        flags_html = " ".join(
            _badge(f, "repost" if f == "repost" else "ghost" if "ghost" in f else "neutral")
            for f in action_job.get("flags") or []
        )
        status = _job_status_badge(action_job)
        cells.append(f'<td class="status-cell"><span class="tag-row">{status} {flags_html}</span></td>')
    if show_board:
        cells.append(f'<td class="col-board">{_board_badge(row_board)}</td>')

    cells.extend(
        [
            f'<td class="col-company">{_company_name_html(company, link=True, link_target=company_link_target, is_ghost=is_ghost)}</td>',
            f'<td class="col-position meta">{_esc(position)}</td>',
            f'<td class="col-title"><strong>{_esc(title)}</strong></td>',
            f'<td class="col-loc">{_esc(location)}</td>',
            f'<td class="col-salary">{_esc(salary or "—")}</td>',
            f'<td class="col-posted">{_esc(posted)}</td>',
            f'<td class="col-scraped">{_esc(scraped_display)}</td>',
        ]
    )
    if show_seen:
        cells.append(f"<td>{action_job.get('seen_count', 1)}</td>")
    if show_key:
        ext = job.get("job_key") or job.get("job_id") or action_job.get("external_id") or ""
        cells.append(f'<td class="col-key"><span class="meta">{_esc(ext)}</span></td>')
    cells.append(f'<td class="col-actions">{actions_html}</td>')

    return (
        f'<tr data-company-slug="{_esc(company_slug)}" data-board="{_esc(row_board)}" '
        f'data-company-text="{_esc(company.lower())}" data-title-text="{_esc(title.lower())}" '
        f'data-application-status="{_esc(app_st)}" {attrs}>{"".join(cells)}</tr>'
    )


def _shared_css():
    return """
* { box-sizing: border-box; }
body { margin: 0; line-height: 1.45; background: var(--bg); color: var(--text); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 20px 24px 48px; }
.wrap-wide { max-width: min(1680px, 98vw); padding: 20px 24px 48px; }
.wrap-full { max-width: min(2200px, 96vw); margin: 0 auto; padding: 20px 32px 48px; }
.nav { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; padding: 12px 14px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); }
.nav a { padding: 6px 12px; border-radius: 999px; border: 1px solid var(--line); color: var(--text); font-size: 12px; font-weight: 600; text-decoration: none; }
.nav a:hover { border-color: var(--accent); color: var(--accent); }
h1 { margin: 0 0 8px; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
.sub { color: var(--muted); margin-bottom: 16px; font-size: 13px; }
code { background: var(--code-bg); padding: 2px 6px; border-radius: 4px; font-size: 12px; border: 1px solid var(--line); }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; box-shadow: var(--shadow); }
.card .num { font-size: 28px; font-weight: 800; line-height: 1.1; }
.card .lbl { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.layout-split { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 960px) { .layout-split { grid-template-columns: 1fr; } }
.side-panel { padding: 12px; }
.side-panel h3 { margin: 0 0 10px; font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: .05em; }
table { width: 100%; border-collapse: collapse; background: var(--panel); font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); text-align: left; }
th { background: var(--head); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); white-space: nowrap; }
.meta { color: var(--muted); font-size: 12px; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 3px; font-size: 10px; font-weight: 700; margin-right: 3px; white-space: nowrap; line-height: 1.3; border: 1px solid var(--line); background: var(--tag-bg); }
.badge-db { border-radius: 3px; white-space: nowrap; padding: 3px 7px; font-size: 10px; }
.badge-board { font-size: 10px; letter-spacing: .03em; text-transform: uppercase; }
.tag-row { display: inline-flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.status-cell { white-space: normal; overflow: visible; text-overflow: clip; min-width: 168px; width: 168px; }
.job-card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; box-shadow: var(--shadow); }
.job-card h3 { margin: 0 0 6px; font-size: 14px; font-weight: 700; }
.job-card .meta { color: var(--muted); font-size: 12px; }
.cards-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
.job-card .job-actions { flex-wrap: nowrap; border-top: 1px solid var(--line); margin-top: 10px; padding-top: 10px; }
@media (max-width: 900px) { .job-card .job-actions { flex-wrap: wrap; } }
.section { margin-top: 28px; }
.section h2 { font-size: 16px; margin-bottom: 10px; font-weight: 700; }
.compare-stack { display: flex; flex-direction: column; gap: 24px; }
.compare-panel h2 { margin-bottom: 10px; font-size: 16px; }
.empty { color: var(--muted); font-style: italic; padding: 24px; text-align: center; border: 1px dashed var(--line); border-radius: var(--radius); }
.table-scroll { overflow: auto; max-height: min(72vh, 900px); border-radius: var(--radius); border: 1px solid var(--line); }
.inner-table { min-width: 1480px; margin: 0; border: none; border-radius: 0; table-layout: fixed; }
.inner-table th { position: sticky; top: 0; z-index: 2; padding: 8px 10px; }
.inner-table td { padding: 0 10px; height: var(--row-h); vertical-align: middle; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; }
.inner-table tr:hover td { background: var(--panel2); }
.inner-table .col-db { width: 100px; min-width: 100px; }
.inner-table .col-status { width: 168px; min-width: 168px; }
.inner-table td.status-cell { overflow: visible; text-overflow: clip; white-space: normal; height: auto; min-height: var(--row-h); }
.inner-table .col-board { width: 72px; min-width: 72px; white-space: nowrap; }
.inner-table .col-title { width: 18%; min-width: 180px; }
.inner-table .col-loc { width: 12%; }
.inner-table .col-salary { width: 11%; }
.inner-table .col-key { width: 9%; font-size: 11px; }
.inner-table .col-actions { width: 280px; min-width: 280px; }
.inner-table .col-company { width: 13%; }
.inner-table .col-position { width: 11%; }
.inner-table .col-posted { width: 8%; }
.inner-table .col-scraped { width: 8%; }
.job-actions-compact { margin-top: 0; padding-top: 0; border-top: none; flex-wrap: nowrap; gap: 4px; align-items: center; }
.job-actions-compact .btn { padding: 3px 8px; font-size: 10px; white-space: nowrap; flex-shrink: 0; }
.job-actions-compact .status-line { display: none; }
.filter-bar { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.filter-btn { background: var(--panel2); color: var(--text); border: 1px solid var(--line); border-radius: 999px; padding: 5px 12px; font-size: 12px; cursor: pointer; white-space: nowrap; }
.filter-btn:hover, .filter-btn.active { border-color: var(--accent); color: var(--accent); }
.job-actions { display: inline-flex; flex-wrap: nowrap; gap: 4px; align-items: center; }
.btn { background: var(--panel2); color: var(--text); border: 1px solid var(--line); border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; white-space: nowrap; }
.btn:hover { border-color: var(--accent); }
.btn-open { color: var(--accent); }
.btn-apply { color: var(--muted); }
.btn-apply.is-done { color: var(--success); border-color: #238636; background: #12261e; cursor: default; }
.btn-apply:disabled { opacity: 1; }
.btn-action[data-action="skipped"] { border-color: #7f1d1d; color: #fca5a5; }
.btn-action[data-action="interviewing"] { border-color: #92400e; color: #fcd34d; }
.job-card.is-applied { border-color: #238636; }
.job-card.is-skipped { opacity: .55; }
.job-card.is-hidden { display: none !important; }
.section.is-hidden { display: none !important; }
.status-line { margin-top: 6px; min-height: 16px; font-size: 11px; color: var(--muted); }
.status-line.ok { color: var(--success); }
.status-line.err { color: #f85149; }
.api-banner { background: var(--accent-soft); border: 1px solid var(--accent-dim); color: var(--text); padding: 10px 14px; border-radius: var(--radius); margin-bottom: 16px; font-size: 12px; }
.api-banner.ok { background: #12261e; border-color: #238636; color: #3fb950; }
.api-banner.hidden { display: none; }
.company-name, .co-link { color: var(--company); font-weight: 700; }
.company-name.company-ghost, a.company-name.company-ghost { color: #f85149 !important; }
a.company-name.company-ghost:hover { color: #ff7b72 !important; }
.co-link:hover { color: var(--accent); }
a.co-link.company-ghost:hover { color: #ff7b72 !important; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--accent); }
th.sortable .sort-ind { opacity: 0.45; font-size: 10px; margin-left: 4px; }
th.sortable.sort-asc .sort-ind::after { content: '▲'; opacity: 1; }
th.sortable.sort-desc .sort-ind::after { content: '▼'; opacity: 1; }
th.sortable:not(.sort-asc):not(.sort-desc) .sort-ind::after { content: '⇅'; }
.card-sort-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 16px; padding: 10px 12px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.card-sort-bar label { font-size: 12px; color: var(--muted); }
.card-sort-select { background: var(--panel2); color: var(--text); border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font-size: 12px; }
tr.is-hidden { display: none !important; }
.stat-card.stat-changed { border-color: var(--warn); box-shadow: 0 0 0 1px rgba(255, 180, 84, 0.35); animation: statPulse 1.2s ease 1; }
.stat-delta { font-size: 13px; font-weight: 700; margin-left: 6px; }
.stat-delta.delta-up { color: var(--success); }
.stat-delta.delta-down { color: #f85149; }
.stat-grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin-bottom: 8px; }
.stat-tile { cursor: pointer; text-align: left; width: 100%; font: inherit; transition: border-color .12s; }
.stat-tile:hover, .stat-tile.open { border-color: var(--accent); }
.stat-hint { display: block; margin-top: 6px; font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.stat-info-panel { display: none; margin: 0 0 16px; padding: 12px 14px; background: var(--accent-soft); border: 1px solid var(--accent); border-radius: var(--radius); font-size: 12px; color: var(--text); line-height: 1.5; }
.stat-info-panel.open { display: block; }
.stat-info-panel strong { color: var(--accent); font-size: 13px; }
@keyframes statPulse { 0%,100% { box-shadow: 0 0 0 0 rgba(255,180,84,0); } 50% { box-shadow: 0 0 0 3px rgba(255,180,84,0.2); } }
.scrape-list, .ghost-list { margin-top: 12px; }
.scrape-list table, .ghost-list table { font-size: 12px; }
.scrape-index-table { table-layout: fixed; width: 100%; min-width: 0; }
.scrape-index-table .col-chevron { width: 32px; text-align: center; color: var(--accent); }
.scrape-index-table .col-query { width: 18%; }
.scrape-index-table .col-location { width: 22%; }
.scrape-index-table .col-jobs { width: 7%; text-align: right; }
.scrape-index-table .col-when { width: 18%; }
.scrape-index-table .col-file { width: 35%; }
.scrape-index-row { cursor: pointer; }
.scrape-index-row:hover td { background: var(--panel2); }
.scrape-index-row.active td { background: var(--accent-soft); border-bottom-color: var(--accent); }
.scrape-index-row.active .col-chevron::before { content: '▾'; }
.scrape-index-row .col-chevron::before { content: '▸'; font-weight: 700; }
.scrape-index-row .cell-clip { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.scrape-index-row .col-query .cell-clip { font-weight: 600; color: var(--text); }
.scrape-index-row .col-file .cell-clip { color: var(--muted); font-size: 11px; }
.scrape-detail-host { margin-top: 14px; }
.scrape-detail-row { display: none; }
.scrape-detail-row.open { display: table-row; }
.scrape-detail-row td { padding: 0; background: var(--panel2); border-bottom: 1px solid var(--line); vertical-align: top; }
.scrape-panel-inner { padding: clamp(10px, 1vw, 18px) clamp(12px, 1.2vw, 20px) clamp(14px, 1.2vw, 22px); }
.scrape-panel { display: none; }
.scrape-panel.active { display: block; }
.scrape-panel-head { margin: 0 0 10px; font-size: 12px; color: var(--muted); }
.scrape-panel-head strong { color: var(--text); }
.metrics-help { margin-top: 14px; padding: 12px 14px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); font-size: 12px; color: var(--muted); }
.metrics-help summary { cursor: pointer; color: var(--text); font-weight: 600; }
.company-block { padding: 14px 16px; border-bottom: 1px solid var(--line); scroll-margin-top: 72px; }
.company-block:last-child { border-bottom: none; }
.company-block h3 { margin: 0 0 8px; font-size: 15px; }
.company-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 10px; }
.company-links a { font-size: 11px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel2); text-decoration: none; }
.company-links a:hover { border-color: var(--accent); color: var(--accent); }
.company-link-google { color: #58a6ff !important; border-color: #1f6feb !important; background: #0d1117 !important; }
.company-link-google:hover { color: #79c0ff !important; border-color: #58a6ff !important; text-decoration: none; }
.company-link-indeed { color: #ff6ec7 !important; border-color: #d633a8 !important; background: #1a0a14 !important; }
.company-link-indeed:hover { color: #ff9edd !important; border-color: #ff6ec7 !important; text-decoration: none; }
.company-index-row { cursor: pointer; scroll-margin-top: clamp(64px, 8vh, 96px); }
.company-index-row:hover td { background: var(--panel2); }
.company-index-row.active td { background: var(--accent-soft); border-bottom-color: var(--accent); }
.company-index-row.is-linked-target td { background: #0d2137; box-shadow: inset 0 0 0 2px #1f6feb; border-bottom-color: #1f6feb; }
.company-index-row.is-linked-target .company-name { color: #58a6ff !important; font-weight: 800; }
.company-index-row.is-linked-target .company-name.company-ghost { color: #ff7b72 !important; }
.company-index-row.is-linked-target .col-chevron::before { color: #58a6ff; }
.company-index-row.is-linked-target.active td { animation: companyLinkPulse 2.5s ease 3; }
.company-detail-row.is-linked-detail > td { box-shadow: inset 4px 0 0 #1f6feb; }
@keyframes companyLinkPulse { 0%,100% { box-shadow: inset 0 0 0 2px #1f6feb, 0 0 0 0 rgba(88,166,255,0); } 50% { box-shadow: inset 0 0 0 2px #1f6feb, 0 0 0 8px rgba(88,166,255,0.22); } }
.company-target-banner { display: none; margin: 0 0 clamp(12px, 1.5vw, 18px); padding: 10px 14px; background: #0d2137; border: 1px solid #1f6feb; border-radius: var(--radius); font-size: clamp(0.78rem, 0.7rem + 0.2vw, 0.95rem); color: var(--text); }
.company-target-banner.open { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.company-target-banner .from-tab { color: #79c0ff; font-weight: 700; }
.company-target-banner strong { color: #58a6ff; }
.company-target-banner .company-target-dismiss { margin-left: auto; color: #79c0ff; border-color: #1f6feb; background: #0a1628; font-size: 11px; padding: 4px 10px; cursor: pointer; }
.company-target-banner .company-target-dismiss:hover { border-color: #58a6ff; color: #58a6ff; }
a.co-link-json.co-link-active { color: #58a6ff !important; text-decoration: underline; text-underline-offset: 3px; }
a.co-link-sqlite.co-link-active { color: #3fb950 !important; text-decoration: underline; text-underline-offset: 3px; }
.company-index-row.active .col-chevron::before { content: '▾'; }
.company-index-row .col-chevron::before { content: '▸'; font-weight: 700; color: var(--accent); }
.company-detail-row { display: none; }
.company-detail-row.open { display: table-row; }
.company-detail-row td { padding: 0; background: var(--panel2); border-bottom: 1px solid var(--line); vertical-align: top; }
.company-panel-inner { padding: clamp(10px, 1vw, 18px) clamp(12px, 1.2vw, 20px) clamp(14px, 1.2vw, 22px); }
.company-panel-meta { margin: 0 0 10px; font-size: 12px; color: var(--muted); line-height: 1.5; }
.company-job-table { min-width: 0; width: 100%; font-size: 12px; }
.company-job-table th, .company-job-table td { padding: 6px 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.company-job-table .col-title { max-width: 42vw; }
.job-link-list { margin: 8px 0 0; padding-left: 18px; font-size: 11px; max-height: 140px; overflow: auto; }
.readme-block { margin-top: 28px; }
.readme-block > h2 { font-size: 16px; margin: 0 0 12px; font-weight: 700; }
.readme-section { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 8px; overflow: hidden; }
.readme-section summary { cursor: pointer; padding: 12px 14px; font-weight: 600; font-size: 13px; list-style: none; display: flex; align-items: center; gap: 8px; user-select: none; }
.readme-section summary::-webkit-details-marker { display: none; }
.readme-section summary::before { content: '▸'; color: var(--accent); font-weight: 700; flex-shrink: 0; }
.readme-section[open] summary::before { content: '▾'; }
.readme-section summary:hover { background: var(--panel2); }
.readme-body { padding: 0 14px 14px; font-size: 12px; color: var(--muted); line-height: 1.55; border-top: 1px solid var(--line); }
.readme-body p { margin: 10px 0; }
.readme-body ul { margin: 8px 0; padding-left: 18px; }
.readme-body li { margin: 4px 0; }
.readme-body strong { color: var(--text); }
.readme-body .file-tag { color: var(--accent); font-size: 11px; }
.cmd-block { margin: 10px 0; padding: 10px 12px; background: var(--code-bg); border: 1px solid var(--line); border-radius: var(--radius); overflow-x: auto; }
.cmd-block .cmd-label { display: block; font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--accent); margin-bottom: 6px; }
.cmd-block code { display: block; white-space: pre-wrap; word-break: break-word; background: transparent; border: none; padding: 0; font-size: 11px; color: var(--text); }
.flow-diagram { margin: 12px 0; padding: 12px; background: var(--code-bg); border: 1px solid var(--line); border-radius: var(--radius); font-size: 11px; line-height: 1.35; color: var(--text); overflow-x: auto; white-space: pre; }
.mermaid-wrap { margin: 12px 0; padding: 16px; background: var(--code-bg); border: 1px solid var(--line); border-radius: var(--radius); overflow-x: auto; }
.mermaid-wrap .mermaid { background: transparent; margin: 0; }
.mermaid-wrap svg { max-width: 100%; height: auto; }
.mermaid-fallback { margin-top: 10px; font-size: 11px; }
.mermaid-fallback summary { cursor: pointer; color: var(--muted); padding: 4px 0; }
.mermaid-fallback[open] summary { color: var(--accent); margin-bottom: 8px; }
.mermaid-offline-note { font-size: 11px; color: var(--muted); margin-top: 8px; }
/* Index page — fluid layout for laptop → ultrawide */
body.index-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.index-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.index-page h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); margin-bottom: clamp(6px, 0.8vw, 14px); }
.index-page > .sub, .index-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); }
.index-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); margin-bottom: clamp(16px, 2vw, 32px); }
.index-page .nav a { font-size: clamp(11px, 0.6rem + 0.35vw, 16px); padding: clamp(6px, 0.45vw, 11px) clamp(10px, 1vw, 20px); }
.index-page .index-grid { display: grid; gap: clamp(10px, 1.4vw, 28px); margin-bottom: clamp(20px, 2.5vw, 40px); grid-template-columns: 1fr; }
@media (min-width: 520px) { .index-page .index-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 900px) { .index-page .index-grid { grid-template-columns: repeat(3, 1fr); } }
@media (min-width: 1200px) { .index-page .index-grid { grid-template-columns: repeat(5, 1fr); } }
.index-page .index-grid .card { padding: clamp(14px, 1.4vw, 32px); min-height: clamp(72px, 7vw, 150px); display: flex; flex-direction: column; justify-content: center; transition: border-color .15s; }
.index-page .index-grid .card:hover { border-color: var(--accent); }
.index-page .index-grid .card h3 { font-size: clamp(0.95rem, 0.8rem + 0.45vw, 1.45rem); margin: 0 0 clamp(4px, 0.5vw, 10px); }
.index-page .index-grid .card .sub { margin: 0; line-height: 1.4; }
.index-page .readme-block { margin-top: clamp(20px, 2.5vw, 48px); }
.index-page .readme-block > h2 { font-size: clamp(1.05rem, 0.9rem + 0.55vw, 1.75rem); margin-bottom: clamp(8px, 1vw, 16px); }
.index-page .readme-section { margin-bottom: clamp(6px, 0.8vw, 12px); }
.index-page .readme-section summary { font-size: clamp(0.82rem, 0.72rem + 0.32vw, 1.12rem); padding: clamp(11px, 1vw, 18px) clamp(12px, 1.2vw, 24px); }
.index-page .readme-body { padding: 0 clamp(12px, 1.2vw, 24px) clamp(12px, 1.2vw, 22px); font-size: clamp(0.76rem, 0.68rem + 0.22vw, 1.05rem); }
.index-page .readme-body .file-tag { font-size: clamp(0.68rem, 0.62rem + 0.18vw, 0.95rem); }
.index-page code { font-size: clamp(0.7rem, 0.62rem + 0.18vw, 0.95rem); }
.index-page .cmd-block { padding: clamp(10px, 1vw, 18px) clamp(12px, 1.2vw, 22px); }
.index-page .cmd-block .cmd-label { font-size: clamp(0.62rem, 0.55rem + 0.15vw, 0.82rem); }
.index-page .cmd-block code { font-size: clamp(0.68rem, 0.6rem + 0.2vw, 0.98rem); }
.index-page .mermaid-wrap { padding: clamp(14px, 2vw, 48px); min-height: clamp(200px, 22vw, 520px); }
.index-page .mermaid-wrap svg { width: 100%; max-width: 100%; height: auto; min-height: clamp(180px, 18vw, 480px); }
.index-page .readme-body .inner-table { min-width: 0; width: 100%; table-layout: auto; font-size: clamp(0.72rem, 0.65rem + 0.18vw, 1rem); }
.index-page .readme-body .inner-table td, .index-page .readme-body .inner-table th { white-space: normal; word-break: break-word; padding: clamp(6px, 0.6vw, 12px); }
.index-page .flow-diagram { font-size: clamp(0.65rem, 0.58rem + 0.18vw, 0.95rem); padding: clamp(10px, 1vw, 18px); }
/* Dashboard page — fluid layout */
body.dashboard-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.dashboard-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.dashboard-page h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); }
.dashboard-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); }
.dashboard-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); }
.dashboard-page .nav a { font-size: clamp(11px, 0.6rem + 0.35vw, 16px); padding: clamp(6px, 0.45vw, 11px) clamp(10px, 1vw, 20px); }
.dashboard-page .stat-grid { gap: clamp(10px, 1.2vw, 22px); grid-template-columns: repeat(auto-fit, minmax(clamp(130px, 11vw, 240px), 1fr)); }
.dashboard-page .stat-grid .num { font-size: clamp(1.4rem, 1rem + 1.2vw, 2.4rem); }
.dashboard-page .stat-grid .lbl { font-size: clamp(0.62rem, 0.55rem + 0.15vw, 0.82rem); }
.dashboard-page .section h2 { font-size: clamp(1rem, 0.85rem + 0.5vw, 1.55rem); }
.dashboard-page .scrape-list.table-scroll { max-height: none; overflow: visible; border: none; }
.dashboard-page .scrape-block .scrape-index-table { width: 100%; }
.dashboard-page .scrape-detail-row .table-scroll { max-height: min(70vh, 900px); border: 1px solid var(--line); border-radius: var(--radius); margin-top: 4px; }
.dashboard-page .ghost-list.table-scroll { max-height: min(75vh, 960px); }
.ghost-list .ghost-table { min-width: 0; width: 100%; table-layout: auto; }
.ghost-list .ghost-table th,
.ghost-list .ghost-table td { white-space: normal; height: auto; min-height: var(--row-h); padding: 8px 10px; overflow: visible; text-overflow: clip; vertical-align: middle; }
.ghost-list .ghost-table th.ghost-col-num,
.ghost-list .ghost-table td.ghost-col-num,
.ghost-list .ghost-table th.ghost-col-score,
.ghost-list .ghost-table td.ghost-col-score { white-space: nowrap; text-align: right; }
.ghost-col-company { width: 18%; min-width: 150px; }
.ghost-col-roles { width: 28%; min-width: 200px; }
.ghost-col-loc { width: 12%; min-width: 90px; }
.ghost-col-num { width: 4.5rem; }
.ghost-col-score { width: 3.5rem; }
.ghost-col-flags { width: 20%; min-width: 260px; }
.ghost-company-cell { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ghost-expand-icon { flex: 0 0 12px; width: 12px; color: var(--accent); font-weight: 700; line-height: 1.2; }
.ghost-index-row { cursor: pointer; }
.ghost-index-row:hover td { background: var(--panel2); }
.ghost-index-row.active td { background: var(--accent-soft); border-bottom-color: var(--accent); }
.ghost-index-row .ghost-expand-icon::before { content: '▸'; }
.ghost-index-row.active .ghost-expand-icon::before { content: '▾'; }
.ghost-index-row.ghost-single { cursor: default; }
.ghost-index-row.ghost-single .ghost-expand-icon { visibility: hidden; }
.ghost-company-cell .company-name { white-space: normal; word-break: break-word; line-height: 1.35; }
.ghost-roles-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; min-width: 0; }
.ghost-role-count { display: inline-flex; align-items: center; background: var(--panel2); border: 1px solid var(--line); border-radius: 999px; padding: 2px 9px; font-size: 11px; color: var(--muted); white-space: nowrap; flex-shrink: 0; }
.ghost-top-role { flex: 1 1 140px; min-width: 0; color: var(--text); font-size: 12px; line-height: 1.35; word-break: break-word; }
.ghost-detail-row { display: none; }
.ghost-detail-row.open { display: table-row; }
.ghost-detail-row td { padding: 8px 12px 14px; background: var(--panel2); border-bottom: 1px solid var(--line); vertical-align: top; width: 100%; }
.ghost-detail-row .ghost-subtable-wrap { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
.ghost-detail-row .ghost-subtable { width: 100%; min-width: 100%; table-layout: fixed; border: none; border-radius: 0; margin: 0; }
.ghost-detail-row .ghost-subtable th,
.ghost-detail-row .ghost-subtable td { white-space: normal; height: auto; padding: 8px 12px; overflow: visible; text-overflow: clip; vertical-align: middle; font-size: 12px; }
.ghost-detail-row .ghost-subtable .ghost-sub-col-title { width: 42%; }
.ghost-detail-row .ghost-subtable .ghost-sub-col-loc { width: 11%; }
.ghost-detail-row .ghost-subtable .ghost-sub-col-num { width: 8%; text-align: right; white-space: nowrap; }
.ghost-detail-row .ghost-subtable .ghost-sub-col-score { width: 7%; text-align: right; white-space: nowrap; }
.ghost-detail-row .ghost-subtable .ghost-sub-col-flags { width: 32%; min-width: 280px; }
.ghost-flags-cell { white-space: nowrap; overflow: visible; vertical-align: middle; }
.ghost-flags-row { display: inline-flex; flex-direction: row; flex-wrap: nowrap; align-items: center; gap: 5px; white-space: nowrap; }
.ghost-flags-row .badge { margin: 0; flex: 0 0 auto; }
/* Screenshot gallery */
.shot-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; align-items: center; }
.shot-strip-thumb { width: 120px; height: 72px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); display: block; }
.shot-strip-link:hover .shot-strip-thumb { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.shot-strip-more { font-size: 11px; color: var(--muted); padding: 4px 8px; }
.shot-session { margin-bottom: 28px; scroll-margin-top: 80px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.shot-session:last-child { border-bottom: none; }
.shot-session-head { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; margin-bottom: 10px; }
.shot-session-head h3 { margin: 0; font-size: 15px; }
.shot-session-meta { font-size: 12px; color: var(--muted); }
.shot-session-meta code { font-size: 11px; }
.shot-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.shot-gallery-thumb { display: block; border-radius: 8px; overflow: hidden; border: 1px solid var(--line); background: var(--panel2); text-decoration: none; color: inherit; }
.shot-gallery-thumb img { width: 100%; aspect-ratio: 16/10; object-fit: cover; display: block; }
.shot-gallery-thumb:hover { border-color: var(--accent); }
.shot-gallery-cap { font-size: 10px; color: var(--muted); padding: 4px 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.shot-kind-tag { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin-right: 6px; }
#shot-lightbox { padding: 0; border: none; background: rgba(0,0,0,.88); max-width: 96vw; max-height: 96vh; color: #fff; }
#shot-lightbox::backdrop { background: rgba(0,0,0,.6); }
#shot-lightbox img { display: block; max-width: 94vw; max-height: 86vh; object-fit: contain; margin: 0 auto; }
.shot-lightbox-cap { font-size: 12px; padding: 10px 14px; text-align: center; }
body.screenshots-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.screenshots-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.screenshots-page h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); }
.screenshots-summary { display: flex; flex-wrap: wrap; gap: 10px 20px; margin-bottom: 20px; font-size: 13px; color: var(--muted); }
/* Jobs page — fluid layout + filters in top bar beside title */
body.jobs-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.jobs-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.jobs-topbar { display: flex; flex-wrap: wrap; align-items: flex-start; gap: clamp(12px, 1.5vw, 28px); margin-bottom: clamp(6px, 0.8vw, 12px); }
.jobs-topbar-left { flex: 0 0 auto; min-width: 200px; }
.jobs-topbar h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); margin: 0; flex: 0 0 auto; white-space: nowrap; }
.jobs-filter-wrap { flex: 1 1 520px; display: flex; flex-wrap: wrap; align-items: center; gap: clamp(10px, 1.2vw, 18px) clamp(16px, 2vw, 32px); min-width: 0; }
.jobs-filter-group { display: flex; flex-wrap: wrap; align-items: center; gap: clamp(6px, 0.6vw, 10px); }
.jobs-filter-label { font-size: clamp(10px, 0.55rem + 0.15vw, 12px); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); white-space: nowrap; min-width: 3.5rem; }
.jobs-page .jobs-filter-bar,
.jobs-page .jobs-board-filter-bar { display: flex; flex-wrap: wrap; gap: clamp(4px, 0.45vw, 8px); margin-bottom: 0; justify-content: flex-start; flex: 1 1 auto; min-width: 0; }
.jobs-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); margin-bottom: clamp(12px, 1.5vw, 20px); }
.jobs-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); margin-bottom: clamp(16px, 2vw, 28px); }
.jobs-page .nav a { font-size: clamp(11px, 0.6rem + 0.35vw, 16px); padding: clamp(6px, 0.45vw, 11px) clamp(10px, 1vw, 20px); }
.jobs-page .filter-btn { font-size: clamp(10px, 0.55rem + 0.22vw, 13px); padding: clamp(4px, 0.35vw, 7px) clamp(8px, 0.75vw, 14px); white-space: nowrap; }
.jobs-table-panel { min-width: 0; width: 100%; }
.jobs-page .table-scroll { max-height: min(80vh, calc(100vh - 180px)); width: 100%; }
.jobs-page .inner-table { font-size: clamp(0.72rem, 0.62rem + 0.2vw, 0.95rem); }
.jobs-page .inner-table th { font-size: clamp(0.62rem, 0.55rem + 0.12vw, 0.78rem); padding: clamp(6px, 0.6vw, 10px); }
.jobs-page .inner-table td { height: clamp(32px, 3.2vw, var(--row-h)); padding: 0 clamp(6px, 0.6vw, 10px); }
.jobs-page #jobs-table tbody tr.is-linked-target td { background: #12261e; box-shadow: inset 0 0 0 2px #238636; border-bottom-color: #238636; }
.jobs-page #jobs-table tbody tr.is-linked-target .company-name { color: #3fb950 !important; font-weight: 800; }
/* Search page — reuse jobs layout + text query bar */
body.search-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.search-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.search-page h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); margin: 0; }
.search-topbar { display: flex; flex-wrap: wrap; align-items: flex-start; gap: clamp(12px, 1.5vw, 28px); margin-bottom: clamp(8px, 1vw, 14px); }
.search-controls { flex: 1 1 520px; display: flex; flex-wrap: wrap; align-items: center; gap: clamp(10px, 1.2vw, 18px); min-width: 0; }
.search-input-wrap { flex: 1 1 280px; min-width: 220px; }
.search-input { width: 100%; padding: clamp(8px, 0.7vw, 12px) clamp(10px, 0.9vw, 14px); border-radius: var(--radius); border: 1px solid var(--line); background: var(--panel); color: var(--text); font-size: clamp(13px, 0.7rem + 0.2vw, 16px); }
.search-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.search-mode-group { display: flex; flex-wrap: wrap; align-items: center; gap: clamp(6px, 0.6vw, 10px); }
.search-mode-label { font-size: clamp(10px, 0.55rem + 0.15vw, 12px); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); white-space: nowrap; }
.search-page .filter-btn { font-size: clamp(10px, 0.55rem + 0.22vw, 13px); padding: clamp(4px, 0.35vw, 7px) clamp(8px, 0.75vw, 14px); white-space: nowrap; }
.search-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); margin-bottom: clamp(12px, 1.5vw, 20px); }
.search-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); margin-bottom: clamp(16px, 2vw, 28px); }
.search-page .table-scroll { max-height: min(80vh, calc(100vh - 220px)); width: 100%; }
.search-page .inner-table { font-size: clamp(0.72rem, 0.62rem + 0.2vw, 0.95rem); }
.search-result-count { font-weight: 600; color: var(--text); }
.jobs-pagination, .search-pagination { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin-bottom: 12px; }
.jobs-pagination .filter-btn, .search-pagination .filter-btn { font-size: 12px; }
.scrape-lazy-body .meta { margin: 8px 0 0; }
.jobs-page #jobs-table tbody tr.is-linked-target .company-name.company-ghost { color: #ff7b72 !important; }
a.co-link-json.company-ghost.co-link-active, a.co-link-sqlite.company-ghost.co-link-active { color: #ff7b72 !important; }
.jobs-page #jobs-table tbody tr.is-linked-target { scroll-margin-top: clamp(64px, 8vh, 96px); animation: jobLinkPulse 2.5s ease 3; }
@keyframes jobLinkPulse { 0%,100% { box-shadow: inset 0 0 0 0 rgba(63,185,80,0); } 50% { box-shadow: inset 0 0 0 3px rgba(63,185,80,0.22); } }
.job-target-banner { display: none; margin: 0 0 clamp(12px, 1.5vw, 18px); padding: 10px 14px; background: #12261e; border: 1px solid #238636; border-radius: var(--radius); font-size: clamp(0.78rem, 0.7rem + 0.2vw, 0.95rem); color: var(--text); }
.job-target-banner.open { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.job-target-banner .from-tab { color: #6ee7b7; font-weight: 700; }
.job-target-banner strong { color: #3fb950; }
.job-target-banner .job-target-dismiss { margin-left: auto; color: #6ee7b7; border-color: #238636; background: #0d1f14; font-size: 11px; padding: 4px 10px; cursor: pointer; }
.job-target-banner .job-target-dismiss:hover { border-color: #3fb950; color: #3fb950; }
.job-target-banner .job-target-dismiss:hover { border-color: #3fb950; color: #3fb950; }
@media (max-width: 640px) {
  .jobs-topbar { flex-direction: column; align-items: stretch; }
  .jobs-page .jobs-filter-bar { justify-content: flex-start; flex-basis: auto; }
}
/* Companies page — fluid layout + inline expand rows */
body.companies-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.companies-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.companies-page h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); margin-bottom: clamp(6px, 0.8vw, 12px); }
.companies-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); margin-bottom: clamp(12px, 1.5vw, 20px); }
.companies-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); margin-bottom: clamp(16px, 2vw, 28px); }
.companies-page .nav a { font-size: clamp(11px, 0.6rem + 0.35vw, 16px); padding: clamp(6px, 0.45vw, 11px) clamp(10px, 1vw, 20px); }
.companies-page .company-index-table { width: 100%; min-width: 0; table-layout: fixed; }
.companies-page .company-index-table .col-chevron { width: 32px; text-align: center; }
.companies-page .company-index-table .col-jobs { width: 72px; text-align: right; }
.companies-page .company-index-table .col-loc { width: 28%; }
.companies-page .company-index-table .col-pos { width: 28%; }
.companies-page .table-scroll { max-height: none; width: 100%; overflow: visible; border: none; }
.companies-page .company-detail-row .table-scroll { max-height: min(50vh, 480px); border: 1px solid var(--line); border-radius: var(--radius); margin-top: 8px; overflow: auto; }
.companies-page .company-links a { font-size: clamp(10px, 0.55rem + 0.2vw, 12px); padding: clamp(4px, 0.4vw, 7px) clamp(8px, 0.8vw, 12px); }
/* Cards page — fluid layout */
body.cards-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.cards-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.cards-topbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: clamp(10px, 1.5vw, 24px); margin-bottom: clamp(6px, 0.8vw, 12px); }
.cards-topbar h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); margin: 0; flex: 0 0 auto; white-space: nowrap; }
.cards-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); margin-bottom: clamp(10px, 1.2vw, 16px); }
.cards-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); margin-bottom: clamp(16px, 2vw, 28px); }
.cards-page .nav a { font-size: clamp(11px, 0.6rem + 0.35vw, 16px); padding: clamp(6px, 0.45vw, 11px) clamp(10px, 1vw, 20px); }
.cards-page .cards-filter-bar { display: flex; flex-wrap: wrap; gap: clamp(4px, 0.45vw, 8px); margin-bottom: 0; justify-content: flex-end; flex: 1 1 320px; min-width: 0; }
.cards-page .filter-btn { font-size: clamp(10px, 0.55rem + 0.22vw, 13px); padding: clamp(4px, 0.35vw, 7px) clamp(8px, 0.75vw, 14px); white-space: nowrap; }
.cards-page .card-sort-bar { gap: clamp(8px, 1vw, 14px); margin-bottom: clamp(14px, 1.5vw, 22px); padding: clamp(8px, 1vw, 14px) clamp(10px, 1.1vw, 16px); }
.cards-page .card-sort-bar label { font-size: clamp(11px, 0.6rem + 0.2vw, 13px); }
.cards-page .card-sort-select { font-size: clamp(11px, 0.6rem + 0.2vw, 13px); padding: clamp(4px, 0.4vw, 8px) clamp(6px, 0.6vw, 10px); }
.cards-page .section { margin-top: clamp(20px, 2.5vw, 36px); }
.cards-page .section h2 { font-size: clamp(1rem, 0.85rem + 0.45vw, 1.45rem); margin-bottom: clamp(8px, 1vw, 14px); }
.cards-page .cards-grid { gap: clamp(10px, 1.2vw, 22px); grid-template-columns: repeat(auto-fill, minmax(clamp(260px, 22vw, 420px), 1fr)); }
.cards-page .job-card { padding: clamp(12px, 1.2vw, 22px); }
.cards-page .job-card h3 { font-size: clamp(0.9rem, 0.78rem + 0.35vw, 1.15rem); margin-bottom: clamp(4px, 0.5vw, 8px); }
.cards-page .job-card .meta { font-size: clamp(0.72rem, 0.64rem + 0.18vw, 0.95rem); line-height: 1.45; }
.cards-page .job-card .btn { font-size: clamp(9px, 0.5rem + 0.18vw, 11px); padding: clamp(3px, 0.3vw, 6px) clamp(6px, 0.55vw, 10px); }
@media (max-width: 640px) {
  .cards-topbar { flex-direction: column; align-items: stretch; }
  .cards-page .cards-filter-bar { justify-content: flex-start; flex-basis: auto; }
}
/* Compare page — fluid layout + side-by-side panels */
body.compare-page { font-size: clamp(13px, 0.55vw + 11px, 18px); }
.compare-page.wrap { width: 100%; max-width: none; margin: 0; padding: clamp(16px, 2vh, 36px) clamp(16px, 3.5vw, 72px) clamp(28px, 4vh, 72px); }
.compare-page h1 { font-size: clamp(1.35rem, 1rem + 1.4vw, 2.75rem); margin-bottom: clamp(6px, 0.8vw, 12px); }
.compare-page .sub { font-size: clamp(0.78rem, 0.65rem + 0.35vw, 1.1rem); }
.compare-page .nav { gap: clamp(6px, 0.7vw, 14px); padding: clamp(10px, 1.2vw, 20px); margin-bottom: clamp(16px, 2vw, 28px); }
.compare-page .nav a { font-size: clamp(11px, 0.6rem + 0.35vw, 16px); padding: clamp(6px, 0.45vw, 11px) clamp(10px, 1vw, 20px); }
.compare-page .compare-split { display: grid; gap: clamp(12px, 1.5vw, 24px); grid-template-columns: 1fr; align-items: stretch; margin-bottom: clamp(20px, 2.5vw, 32px); }
@media (min-width: 1100px) {
  .compare-page .compare-split { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
}
.compare-page .compare-panel { min-width: 0; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: clamp(12px, 1.2vw, 18px); display: flex; flex-direction: column; }
.compare-page .compare-panel h2 { font-size: clamp(0.95rem, 0.82rem + 0.4vw, 1.25rem); margin: 0 0 clamp(4px, 0.5vw, 8px); }
.compare-page .compare-panel .sub { margin-bottom: clamp(8px, 1vw, 12px); font-size: clamp(0.72rem, 0.64rem + 0.18vw, 0.92rem); }
.compare-page .compare-panel .table-scroll { flex: 1 1 auto; overflow: auto; max-height: min(72vh, calc(100vh - 260px)); border: 1px solid var(--line); border-radius: var(--radius); }
.compare-page .compare-panel .inner-table { font-size: clamp(0.68rem, 0.6rem + 0.16vw, 0.88rem); min-width: 1280px; }
.compare-page .compare-panel .inner-table th { font-size: clamp(0.6rem, 0.52rem + 0.12vw, 0.75rem); padding: clamp(5px, 0.5vw, 9px); }
.compare-page .compare-panel .inner-table td { padding: 0 clamp(5px, 0.5vw, 9px); height: clamp(30px, 3vw, var(--row-h)); }
.compare-page .section h2 { font-size: clamp(1rem, 0.85rem + 0.5vw, 1.45rem); }
.compare-page .section .grid { gap: clamp(10px, 1.2vw, 18px); grid-template-columns: repeat(auto-fit, minmax(clamp(120px, 10vw, 200px), 1fr)); }
.compare-page .section .card .num { font-size: clamp(1.3rem, 0.95rem + 1vw, 2.2rem); }
.compare-page .section .card .lbl { font-size: clamp(0.62rem, 0.55rem + 0.12vw, 0.78rem); }
.compare-page .section .card { padding: clamp(12px, 1.1vw, 18px); }
"""


def _base_css(theme="console"):
    if theme == "light":
        return """
:root { --bg:#f8fafc; --panel:#fff; --panel2:#f1f5f9; --text:#0f172a; --muted:#64748b; --line:#e2e8f0; --accent:#2563eb; --accent-dim:#93c5fd; --accent-soft:#dbeafe; --company:#b45309; --head:#f1f5f9; --table-head:#f1f5f9; --code-bg:#e2e8f0; --btn-bg:#f1f5f9; --btn-hover:#e2e8f0; --tag-bg:#f1f5f9; --success:#059669; --warn:#d97706; --shadow:0 1px 3px rgba(15,23,42,.08); --radius:8px; --row-h:40px; }
body { font-family: system-ui, sans-serif; font-size: 14px; }
"""
    return """
:root {
  --bg:#0a0e14; --panel:#111820; --panel2:#151c26; --text:#c9d1d9; --muted:#7d8590;
  --line:#21262d; --accent:#ffb454; --accent-dim:#6e4a12; --accent-soft:#3d2a0a;
  --company:#ffd580; --head:#0d1117; --table-head:#0d1117; --code-bg:#0d1117;
  --btn-bg:#151c26; --btn-hover:#1a2332; --tag-bg:#1a2332;
  --success:#3fb950; --warn:#ffb454;
  --shadow:inset 0 1px 0 rgba(255,255,255,.04);
  --radius:6px; --row-h:36px;
}
body { font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace; font-size: 13px; }
"""


def _mermaid_init_js():
    return """
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {
  if (typeof mermaid === 'undefined') return;
  var vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  var fs = Math.min(18, Math.max(11, Math.round(vw / 140)));
  mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    securityLevel: 'loose',
    themeVariables: {
      darkMode: true,
      background: '#0a0e14',
      primaryColor: '#151c26',
      primaryTextColor: '#c9d1d9',
      primaryBorderColor: '#ffb454',
      secondaryColor: '#111820',
      secondaryTextColor: '#c9d1d9',
      secondaryBorderColor: '#21262d',
      tertiaryColor: '#1a2332',
      tertiaryTextColor: '#7d8590',
      tertiaryBorderColor: '#21262d',
      lineColor: '#7d8590',
      textColor: '#c9d1d9',
      mainBkg: '#151c26',
      nodeBorder: '#ffb454',
      clusterBkg: '#111820',
      clusterBorder: '#21262d',
      titleColor: '#ffb454',
      edgeLabelBackground: '#0a0e14',
      fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
      fontSize: fs + 'px',
    },
    flowchart: { htmlLabels: true, curve: 'basis', padding: Math.max(12, Math.round(vw / 100)), nodeSpacing: Math.max(30, Math.round(vw / 50)), rankSpacing: Math.max(40, Math.round(vw / 40)) },
  });
  mermaid.run({ querySelector: '.mermaid', suppressErrors: true }).catch(function() {
    document.querySelectorAll('.mermaid-fallback').forEach(function(el) { el.open = true; });
  });
});
</script>"""


def _data_flow_mermaid_html(ascii_fallback):
    diagram = """flowchart TB
  subgraph S1["① Collection"]
    Chrome["Chrome profile"]
    Warm["warm_indeed_profile.py"]
    Attach["run_indeed_attach.sh"]
    Main["src/main.py"]
    Scraper["scraper_indeed.py"]
  end
  subgraph S2["② Artifacts"]
    JSON["artifacts/json/*.json"]
  end
  subgraph S3["③ Aggregation"]
    Store["job_store.py"]
    DB[("artifacts/jobs.db")]
  end
  subgraph S4["④ Reports"]
    HTMLGen["job_report_html.py"]
    HTML["artifacts/html/*.html"]
    Server["generate_job_reports.py --serve"]
    Apps[("applications table")]
  end

  Chrome --> Warm
  Attach --> Main
  Warm --> Main
  Main --> Scraper
  Scraper --> JSON
  JSON --> Store
  JSON --> HTMLGen
  Store --> DB
  HTMLGen --> DB
  DB --> HTML
  HTML --> Server
  Server --> Apps
  DB -.-> Apps"""
    return f"""<div class="mermaid-wrap">
  <pre class="mermaid">{diagram}</pre>
  <p class="mermaid-offline-note">Diagram rendered by Mermaid.js (CDN). Needs network on first load; use ASCII fallback if offline.</p>
  <details class="mermaid-fallback">
    <summary>ASCII fallback</summary>
    <pre class="flow-diagram">{_esc(ascii_fallback)}</pre>
  </details>
</div>"""


def _shell(title, body, theme="console", nav_links=None, interactive=True, layout_wide=False, layout_full=False, mermaid=False, page_class="", extra_script=""):
    nav = nav_links or []
    nav_html = ""
    if nav:
        nav_html = '<nav class="nav">' + "".join(
            f'<a href="{_esc(href)}">{_esc(label)}</a>' for label, href in nav
        ) + "</nav>"

    css = _base_css(theme) + _shared_css()
    banner_html = ""
    script_html = ""
    if interactive:
        banner_html = """
<div id="api-banner" class="api-banner">
  Card actions save to SQLite when the report server is running:
  <code>python3 modules/generate_job_reports.py --serve</code>
  then open <a href="http://127.0.0.1:8765/report_cards.html">http://127.0.0.1:8765/report_cards.html</a>
</div>"""
        script_html = _interactive_js()

    if mermaid:
        script_html += _mermaid_init_js()
    if extra_script:
        script_html += extra_script

    wrap_class = "wrap wrap-full" if layout_full else ("wrap wrap-wide" if layout_wide else "wrap")
    if page_class:
        wrap_class += f" {_esc(page_class)}"
    body_class = f' class="{_esc(page_class)}"' if page_class else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{_esc(title)}</title>
<style>
{css}
</style>
</head>
<body{body_class}>
<div class="{wrap_class}">
{nav_html}
{banner_html}
{body}
{script_html}
</div>
</body>
</html>"""


def _nav():
    return [
        ("Index", "index.html"),
        ("Dashboard", "report_dashboard.html"),
        ("Jobs", "report_table.html"),
        ("Search", "report_search.html"),
        ("Companies", "report_companies.html"),
        ("Cards", "report_cards.html"),
        ("Screenshots", "report_screenshots.html"),
        ("Compare", "report_compare.html"),
    ]


def _interactive_js():
    return """<script>
(function () {
  const API = (location.protocol.startsWith('http') && location.port)
    ? (location.origin)
    : 'http://127.0.0.1:8765';

  const banner = document.getElementById('api-banner');

  async function checkHealth() {
    try {
      const res = await fetch(API + '/api/health');
      if (!res.ok) throw new Error('bad status');
      if (banner) {
        banner.classList.add('ok');
        banner.innerHTML = 'Connected — actions save to <code>artifacts/jobs.db</code> (Apply / Skip / Interview / Copy)';
      }
    } catch (e) {
      if (banner) banner.classList.remove('hidden');
    }
  }

  function updateApplyButton(scope, status) {
    const root = scope.closest ? (scope.closest('.job-actions') || scope) : scope;
    const btn = root.querySelector && root.querySelector('.btn-apply');
    if (!btn) return;
    const isApplied = status === 'applied';
    btn.textContent = isApplied ? 'Applied' : 'Apply';
    btn.classList.toggle('is-done', isApplied);
    btn.disabled = isApplied;
  }

  function applyCardState(card, status) {
    if (!card) return;
    card.dataset.applicationStatus = status || 'none';
    card.classList.remove('is-applied', 'is-skipped', 'is-offer');
    if (status === 'applied') card.classList.add('is-applied');
    if (status === 'offer') card.classList.add('is-offer');
    if (status === 'skipped' || status === 'rejected') card.classList.add('is-skipped');
    updateApplyButton(card, status);
    const actions = card.querySelector('.job-actions');
    if (actions) updateApplyButton(actions, status);
  }

  async function postStatus(container, status) {
    const jobId = container.dataset.jobId;
    const externalId = container.dataset.externalId;
    const board = container.dataset.board || 'indeed';
    const statusLine = container.querySelector('.status-line') || container.parentElement.querySelector('.status-line');
    let url = jobId
      ? `${API}/api/jobs/${jobId}/status`
      : `${API}/api/jobs/by-external/${encodeURIComponent(board)}/${encodeURIComponent(externalId)}/status`;

    if (!jobId && !externalId) {
      if (statusLine) { statusLine.textContent = 'No job id — import JSON to DB first'; statusLine.className = 'status-line err'; }
      return;
    }

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'save failed');
      const card = container.closest('.job-card') || container.closest('tr') || container;
      applyCardState(card, status);
      container.dataset.status = status;
      if (statusLine) { statusLine.textContent = 'Saved: ' + status; statusLine.className = 'status-line ok'; }
    } catch (err) {
      if (statusLine) {
        statusLine.textContent = 'Start server: python3 modules/generate_job_reports.py --serve';
        statusLine.className = 'status-line err';
      }
    }
  }

  function copyJob(container) {
    const card = container.closest('.job-card') || container.closest('tr');
    const title = card.querySelector('h3, .col-title strong, strong')?.textContent?.trim() || '';
    const company = card.querySelector('.company-name, .company-cell')?.textContent?.trim() || '';
    const url = container.querySelector('.btn-open')?.href || '';
    const text = [title, company, url].filter(Boolean).join('\\n');
    navigator.clipboard.writeText(text).then(() => {
      const statusLine = container.querySelector('.status-line') || container.parentElement.querySelector('.status-line');
      if (statusLine) { statusLine.textContent = 'Copied to clipboard'; statusLine.className = 'status-line ok'; }
    }).catch(() => {});
  }

  function sortValue(el, key, type) {
    let val = el.dataset[key] ?? '';
    if (type === 'num') return parseFloat(val) || 0;
    if (type === 'date') return Date.parse(val) || 0;
    return String(val).toLowerCase();
  }

  function sortTableByHeader(th) {
    const table = th.closest('table');
    if (!table) return;
    const key = th.dataset.sort;
    const type = th.dataset.sortType || 'text';
    const tbody = table.tBodies[0];
    if (!tbody || !key) return;
    const rows = Array.from(tbody.querySelectorAll('tr')).filter((row) => !row.querySelector('.empty'));
    const asc = th.dataset.sortDir !== 'asc';
    table.querySelectorAll('th.sortable').forEach((header) => {
      header.classList.remove('sort-asc', 'sort-desc');
      if (header !== th) delete header.dataset.sortDir;
    });
    th.dataset.sortDir = asc ? 'asc' : 'desc';
    th.classList.add(asc ? 'sort-asc' : 'sort-desc');
    const dir = asc ? 1 : -1;
    rows.sort((a, b) => {
      const av = sortValue(a, key, type);
      const bv = sortValue(b, key, type);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    rows.forEach((row) => tbody.appendChild(row));
  }

  function initTableSort() {
    document.querySelectorAll('table.sortable-table th.sortable').forEach((th) => {
      th.addEventListener('click', (ev) => {
        ev.stopPropagation();
        sortTableByHeader(th);
      });
    });
  }

  function applyStatusFilter(filter, selector) {
    const boardFilter = window.__activeBoardFilter || 'all';
    document.querySelectorAll(selector).forEach((el) => {
      const st = el.dataset.applicationStatus || 'none';
      const board = el.dataset.board || 'indeed';
      let show = true;
      if (filter === 'open') show = !st || st === 'none';
      else if (filter === 'applied') show = st === 'applied';
      else if (filter === 'skipped') show = st === 'skipped' || st === 'rejected';
      else if (filter === 'interview') show = st === 'interviewing';
      else if (filter === 'offer') show = st === 'offer';
      else if (filter === 'ghost') show = (el.dataset.flags || '').includes('ghost_candidate');
      if (boardFilter !== 'all' && board !== boardFilter) show = false;
      el.classList.toggle('is-hidden', !show);
    });

    document.querySelectorAll('#company-sections .section').forEach((section) => {
      const visible = section.querySelectorAll('.job-card:not(.is-hidden)').length;
      section.classList.toggle('is-hidden', visible === 0);
    });

    const wrap = document.getElementById('company-sections');
    if (wrap) {
      let empty = wrap.querySelector('.filter-empty');
      const anyVisible = wrap.querySelectorAll('.job-card:not(.is-hidden)').length > 0;
      if (!anyVisible && filter !== 'all') {
        if (!empty) {
          empty = document.createElement('div');
          empty.className = 'empty filter-empty';
          empty.textContent = 'No jobs match this filter.';
          wrap.appendChild(empty);
        }
      } else if (empty) {
        empty.remove();
      }
    }

    const jobsPanel = document.querySelector('.jobs-table-panel .table-scroll');
    if (jobsPanel) {
      let empty = jobsPanel.querySelector('.filter-empty');
      const jobRows = document.querySelectorAll('#jobs-table tbody tr[data-application-status]');
      const anyJobVisible = Array.from(jobRows).some((row) => !row.classList.contains('is-hidden'));
      if (!anyJobVisible && jobRows.length) {
        if (!empty) {
          empty = document.createElement('div');
          empty.className = 'empty filter-empty';
          jobsPanel.appendChild(empty);
        }
        const boardLabel = boardFilter === 'all' ? 'all sources' : boardFilter;
        empty.textContent = filter === 'all' && boardFilter === 'all'
          ? 'No jobs to show.'
          : 'No jobs match filter (' + filter + ', ' + boardLabel + ').';
      } else if (empty) {
        empty.remove();
      }
    }
  }

  function initFilters() {
    document.querySelectorAll('.filter-bar:not([data-api-filter])').forEach((bar) => {
      const target = bar.dataset.filterTarget || '.job-card[data-application-status]';
      bar.querySelectorAll('.filter-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          bar.querySelectorAll('.filter-btn').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          if (btn.dataset.boardFilter !== undefined) {
            window.__activeBoardFilter = btn.dataset.boardFilter || 'all';
            const statusBar = document.querySelector('.jobs-filter-bar');
            const activeStatus = statusBar?.querySelector('.filter-btn.active')?.dataset.filter || 'all';
            applyStatusFilter(activeStatus, target);
            return;
          }
          applyStatusFilter(btn.dataset.filter, target);
        });
      });
    });
  }

  function initStatTiles() {
    document.querySelectorAll('.stat-grid').forEach((grid) => {
      const panel = grid.nextElementSibling;
      if (!panel || !panel.classList.contains('stat-info-panel')) return;
      grid.querySelectorAll('.stat-tile').forEach((btn) => {
        btn.addEventListener('click', () => {
          const tip = btn.dataset.statTip || '';
          const label = btn.dataset.statLabel || 'Metric';
          const closing = btn.classList.contains('open');
          grid.querySelectorAll('.stat-tile').forEach((b) => b.classList.remove('open'));
          panel.classList.remove('open');
          panel.innerHTML = '';
          if (closing || !tip) return;
          btn.classList.add('open');
          panel.innerHTML = '<strong>' + label + '</strong><p style="margin:8px 0 0">' + tip + '</p>';
          panel.classList.add('open');
        });
      });
    });
  }

  function debounce(fn, ms) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  async function fetchJobsApi(params) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') qs.set(key, String(value));
    });
    const res = await fetch(API + '/api/jobs?' + qs.toString());
    if (!res.ok) throw new Error('fetch failed');
    return res.json();
  }

  function bindLoadedJobRows(root) {
    (root || document).querySelectorAll('.job-actions').forEach((actions) => {
      applyCardState(actions.closest('tr') || actions.closest('.job-card') || actions, actions.dataset.status || 'none');
    });
  }

  function initJobsApi() {
    const table = document.getElementById('jobs-table');
    if (!table || table.dataset.apiLoad !== '1') return;
    const tbody = table.querySelector('tbody');
    const countEl = document.getElementById('jobs-result-count');
    const prevBtn = document.getElementById('jobs-prev');
    const nextBtn = document.getElementById('jobs-next');
    const pageInfo = document.getElementById('jobs-page-info');
    const state = { offset: 0, limit: 50, status: 'all', board: 'all', total: 0 };

    async function load() {
      if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="empty">Loading…</td></tr>';
      try {
        const data = await fetchJobsApi({
          field: 'both',
          board: state.board,
          status: state.status,
          limit: state.limit,
          offset: state.offset,
        });
        state.total = data.total || 0;
        if (tbody) tbody.innerHTML = data.rows_html || '<tr><td colspan="12" class="empty">No jobs found.</td></tr>';
        bindLoadedJobRows(tbody);
        const start = state.total ? state.offset + 1 : 0;
        const end = Math.min(state.offset + state.limit, state.total);
        if (pageInfo) pageInfo.textContent = start + '–' + end + ' of ' + state.total;
        if (countEl) countEl.textContent = state.total + ' listings total';
        if (prevBtn) prevBtn.disabled = state.offset <= 0;
        if (nextBtn) nextBtn.disabled = state.offset + state.limit >= state.total;
      } catch (e) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="empty">Start server: python3 modules/generate_job_reports.py --serve</td></tr>';
        if (pageInfo) pageInfo.textContent = 'Server required';
      }
    }

    document.querySelectorAll('.jobs-api-status-bar .filter-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.jobs-api-status-bar .filter-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.status = btn.dataset.filter || 'all';
        state.offset = 0;
        load();
      });
    });
    document.querySelectorAll('.jobs-api-board-bar .filter-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.jobs-api-board-bar .filter-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.board = btn.dataset.boardFilter || 'all';
        state.offset = 0;
        load();
      });
    });
    if (prevBtn) prevBtn.addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
    if (nextBtn) nextBtn.addEventListener('click', () => {
      if (state.offset + state.limit < state.total) { state.offset += state.limit; load(); }
    });
    load();
  }

  function initSearchApi() {
    const input = document.getElementById('search-query');
    const table = document.getElementById('search-table');
    if (!input || !table || table.dataset.apiLoad !== '1') return;

    const tbody = table.querySelector('tbody');
    const countEl = document.getElementById('search-result-count');
    const prevBtn = document.getElementById('search-prev');
    const nextBtn = document.getElementById('search-next');
    const pageInfo = document.getElementById('search-page-info');
    const state = { offset: 0, limit: 50, field: 'both', board: 'all', q: '' };

    function activeMode() {
      const btn = document.querySelector('.search-mode-bar .filter-btn.active');
      return btn ? (btn.dataset.searchMode || 'both') : 'both';
    }

    async function load() {
      const q = (input.value || '').trim();
      state.q = q;
      state.field = activeMode();
      const browseBoard = state.board && state.board !== 'all';
      if (!q && !browseBoard) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="empty">Enter a company or job title, or pick a source to browse.</td></tr>';
        if (countEl) countEl.textContent = 'Type to search, or pick a source';
        if (pageInfo) pageInfo.textContent = '';
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;
        return;
      }
      if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="empty">Loading…</td></tr>';
      try {
        const params = {
          field: state.field,
          board: state.board,
          status: 'all',
          limit: state.limit,
          offset: state.offset,
        };
        if (q) params.q = q;
        const data = await fetchJobsApi(params);
        const total = data.total || 0;
        if (tbody) tbody.innerHTML = data.rows_html || '<tr><td colspan="12" class="empty">No jobs match.</td></tr>';
        bindLoadedJobRows(tbody);
        const start = total ? state.offset + 1 : 0;
        const end = Math.min(state.offset + state.limit, total);
        if (countEl) {
          if (q) {
            countEl.textContent = 'Found ' + total + ' match' + (total === 1 ? '' : 'es') + ' for "' + q + '"';
          } else {
            const boardLabel = state.board.charAt(0).toUpperCase() + state.board.slice(1);
            countEl.textContent = boardLabel + ': ' + total + ' listing' + (total === 1 ? '' : 's');
          }
        }
        if (pageInfo) pageInfo.textContent = start + '–' + end + ' of ' + total;
        if (prevBtn) prevBtn.disabled = state.offset <= 0;
        if (nextBtn) nextBtn.disabled = state.offset + state.limit >= total;
      } catch (e) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="empty">Start server: python3 modules/generate_job_reports.py --serve</td></tr>';
      }
    }

    const debouncedLoad = debounce(() => { state.offset = 0; load(); }, 300);
    input.addEventListener('input', debouncedLoad);
    document.querySelectorAll('.search-mode-bar .filter-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.search-mode-bar .filter-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.offset = 0;
        load();
      });
    });
    document.querySelectorAll('.search-board-bar .filter-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.search-board-bar .filter-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.board = btn.dataset.boardFilter || 'all';
        state.offset = 0;
        load();
      });
    });
    if (prevBtn) prevBtn.addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
    if (nextBtn) nextBtn.addEventListener('click', () => { state.offset += state.limit; load(); });
    input.focus();
  }

  async function loadScrapePanel(detailRow) {
    const lazy = detailRow.querySelector('.scrape-lazy-body');
    if (!lazy || lazy.dataset.loaded === '1' || lazy.dataset.loading === '1') return;
    lazy.dataset.loading = '1';
    lazy.innerHTML = '<p class="meta">Loading jobs…</p>';
    try {
      const res = await fetch(API + '/api/scrapes/' + encodeURIComponent(lazy.dataset.filename) + '/jobs');
      if (!res.ok) throw new Error('bad status');
      const data = await res.json();
      lazy.innerHTML = data.table_html || '<div class="empty">No jobs in file</div>';
      lazy.dataset.loaded = '1';
      initTableSort();
      bindLoadedJobRows(lazy);
    } catch (e) {
      lazy.innerHTML = '<p class="empty">Could not load jobs — start report server.</p>';
    }
    lazy.dataset.loading = '0';
  }

  function initScrapeIndex() {
    document.querySelectorAll('.scrape-index-row, .ghost-index-row').forEach((row) => {
      if (row.classList.contains('ghost-single')) return;
      row.addEventListener('click', () => {
        const panelId = row.dataset.panel;
        if (!panelId) return;
        const detailRow = document.getElementById(panelId);
        if (!detailRow) return;
        const opening = !detailRow.classList.contains('open');
        detailRow.classList.toggle('open', opening);
        row.classList.toggle('active', opening);
        if (opening) loadScrapePanel(detailRow);
      });
    });
  }

  function companyNavStorageKey() { return 'indeedCompanyNav'; }
  function jobNavStorageKey() { return 'indeedJobNav'; }

  function navSourceLabel(kind) {
    const tab = pageTabLabel();
    if (tab !== 'Compare') return tab;
    return kind === 'sqlite' ? tab + ' · SQLite' : tab + ' · JSON';
  }

  function pageTabLabel() {
    const cls = document.body.className || '';
    if (cls.indexOf('compare-page') !== -1) return 'Compare';
    if (cls.indexOf('jobs-page') !== -1) return 'Jobs';
    if (cls.indexOf('search-page') !== -1) return 'Search';
    if (cls.indexOf('cards-page') !== -1) return 'Cards';
    if (cls.indexOf('dashboard-page') !== -1) return 'Dashboard';
    return (document.title || 'Report').split('·')[0].trim();
  }

  function rememberCompanyNavigation(link) {
    const href = link.getAttribute('href') || '';
    if (href.indexOf('report_companies.html') === -1) return;
    const hash = (href.split('#')[1] || '').trim();
    if (!hash) return;
    document.querySelectorAll('a.co-link-active').forEach((el) => el.classList.remove('co-link-active'));
    link.classList.add('co-link-active');
    try {
      sessionStorage.setItem(companyNavStorageKey(), JSON.stringify({
        slug: decodeURIComponent(hash),
        name: (link.textContent || '').trim(),
        from: navSourceLabel('json'),
        at: Date.now(),
      }));
    } catch (e) {}
  }

  function rememberJobNavigation(link) {
    const href = link.getAttribute('href') || '';
    if (href.indexOf('report_table.html') === -1) return;
    const hash = (href.split('#')[1] || '').trim();
    if (!hash.startsWith('company-')) return;
    const slug = decodeURIComponent(hash.slice('company-'.length));
    document.querySelectorAll('a.co-link-active').forEach((el) => el.classList.remove('co-link-active'));
    link.classList.add('co-link-active');
    try {
      sessionStorage.setItem(jobNavStorageKey(), JSON.stringify({
        slug: slug,
        name: (link.textContent || '').trim(),
        from: navSourceLabel('sqlite'),
        at: Date.now(),
      }));
    } catch (e) {}
  }

  function readJobNavigation() {
    try {
      const raw = sessionStorage.getItem(jobNavStorageKey());
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || !data.slug) return null;
      if (data.at && Date.now() - data.at > 30 * 60 * 1000) {
        sessionStorage.removeItem(jobNavStorageKey());
        return null;
      }
      return data;
    } catch (e) {
      return null;
    }
  }

  function clearJobLinkTarget() {
    document.querySelectorAll('#jobs-table tbody tr.is-linked-target').forEach((row) => {
      row.classList.remove('is-linked-target');
    });
    const banner = document.getElementById('job-target-banner');
    if (banner) banner.classList.remove('open');
  }

  function readCompanyNavigation() {
    try {
      const raw = sessionStorage.getItem(companyNavStorageKey());
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || !data.slug) return null;
      if (data.at && Date.now() - data.at > 30 * 60 * 1000) {
        sessionStorage.removeItem(companyNavStorageKey());
        return null;
      }
      return data;
    } catch (e) {
      return null;
    }
  }

  function clearCompanyLinkTarget() {
    document.querySelectorAll('.company-index-row.is-linked-target').forEach((row) => {
      row.classList.remove('is-linked-target');
    });
    document.querySelectorAll('.company-detail-row.is-linked-detail').forEach((row) => {
      row.classList.remove('is-linked-detail');
    });
    const banner = document.getElementById('company-target-banner');
    if (banner) banner.classList.remove('open');
  }

  function initCompanyLinks() {
    document.addEventListener('click', function(ev) {
      const jsonLink = ev.target.closest('a.co-link-json');
      if (jsonLink) {
        rememberCompanyNavigation(jsonLink);
        return;
      }
      const sqliteLink = ev.target.closest('a.co-link-sqlite');
      if (sqliteLink) {
        rememberJobNavigation(sqliteLink);
      }
    });
  }

  function initCompanyIndex() {
    document.querySelectorAll('.company-index-row').forEach((row) => {
      row.addEventListener('click', (ev) => {
        if (ev.target.closest('a')) return;
        const panelId = row.dataset.panel;
        if (!panelId) return;
        const detailRow = document.getElementById(panelId);
        if (!detailRow || !detailRow.classList.contains('company-detail-row')) return;
        const opening = !detailRow.classList.contains('open');
        detailRow.classList.toggle('open', opening);
        row.classList.toggle('active', opening);
        if (!row.classList.contains('is-linked-target')) {
          clearCompanyLinkTarget();
        }
      });
    });
  }

  function openCompanyFromHash() {
    const raw = (location.hash || '').replace(/^#/, '').trim();
    if (!raw) return;
    const slug = decodeURIComponent(raw);
    clearCompanyLinkTarget();
    const row = document.getElementById(slug)
      || document.querySelector('.company-index-row[data-company-slug="' + slug.replace(/"/g, '') + '"]');
    if (!row) {
      let banner = document.getElementById('company-target-banner');
      if (document.body.classList.contains('companies-page')) {
        if (!banner) {
          banner = document.createElement('div');
          banner.id = 'company-target-banner';
          banner.className = 'company-target-banner';
          const anchor = document.querySelector('.companies-page.wrap h1');
          if (anchor && anchor.parentNode) {
            anchor.parentNode.insertBefore(banner, anchor.nextSibling);
          }
        }
        banner.innerHTML = 'Company <strong>' + slug + '</strong> was not found in this report. Regenerate HTML reports after scraping/import.';
        banner.classList.add('open');
      }
      return;
    }
    const panelId = row.dataset.panel;
    const detailRow = panelId && document.getElementById(panelId);
    if (detailRow) {
      detailRow.classList.add('open', 'is-linked-detail');
      row.classList.add('active');
    }
    row.classList.add('is-linked-target');
    const nav = readCompanyNavigation();
    const nameEl = row.querySelector('.company-name');
    const label = (nav && nav.name) || (nameEl ? nameEl.textContent.trim() : slug);
    const fromTab = (nav && nav.from) || 'another tab';
    let banner = document.getElementById('company-target-banner');
    if (!banner && document.body.classList.contains('companies-page')) {
      banner = document.createElement('div');
      banner.id = 'company-target-banner';
      banner.className = 'company-target-banner';
      const anchor = document.querySelector('.companies-page.wrap h1');
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(banner, anchor.nextSibling);
      }
      banner.addEventListener('click', function(ev) {
        if (ev.target.closest('.company-target-dismiss')) {
          clearCompanyLinkTarget();
          try { sessionStorage.removeItem(companyNavStorageKey()); } catch (e) {}
        }
      });
    }
    if (banner) {
      banner.innerHTML = 'From <span class="from-tab">' + fromTab + '</span> → <strong>' + label + '</strong>'
        + '<button type="button" class="btn company-target-dismiss">Dismiss highlight</button>';
      banner.classList.add('open');
    }
    window.setTimeout(function() {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 60);
  }

  function initCompanyHash() {
    openCompanyFromHash();
    window.addEventListener('hashchange', openCompanyFromHash);
  }

  function openJobFromHash() {
    if (!document.body.classList.contains('jobs-page')) return;
    const raw = (location.hash || '').replace(/^#/, '').trim();
    if (!raw.startsWith('company-')) return;
    const slug = decodeURIComponent(raw.slice('company-'.length));
    clearJobLinkTarget();
    const rows = Array.from(document.querySelectorAll(
      '#jobs-table tbody tr[data-company-slug="' + slug.replace(/"/g, '') + '"]'
    ));
    if (!rows.length) return;
    rows.forEach((row) => row.classList.add('is-linked-target'));
    const nav = readJobNavigation();
    const label = (nav && nav.name) || rows[0].querySelector('.company-name')?.textContent.trim() || slug;
    const fromTab = (nav && nav.from) || 'another tab';
    let banner = document.getElementById('job-target-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'job-target-banner';
      banner.className = 'job-target-banner';
      const anchor = document.querySelector('.jobs-topbar') || document.querySelector('.jobs-page.wrap h1');
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(banner, anchor.nextSibling);
      }
      banner.addEventListener('click', function(ev) {
        if (ev.target.closest('.job-target-dismiss')) {
          clearJobLinkTarget();
          try { sessionStorage.removeItem(jobNavStorageKey()); } catch (e) {}
        }
      });
    }
    if (banner) {
      banner.innerHTML = 'From <span class="from-tab">' + fromTab + '</span> → <strong>' + label + '</strong>'
        + ' <span class="meta">(' + rows.length + ' job' + (rows.length === 1 ? '' : 's') + ')</span>'
        + '<button type="button" class="btn job-target-dismiss">Dismiss highlight</button>';
      banner.classList.add('open');
    }
    window.setTimeout(function() {
      rows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 60);
  }

  function initJobHash() {
    openJobFromHash();
    window.addEventListener('hashchange', openJobFromHash);
  }

  function sortCards(key, type) {
    document.querySelectorAll('.cards-grid').forEach((grid) => {
      const cards = Array.from(grid.querySelectorAll('.job-card'));
      cards.sort((a, b) => {
        const av = sortValue(a, key, type);
        const bv = sortValue(b, key, type);
        if (av < bv) return -1;
        if (av > bv) return 1;
        return 0;
      });
      cards.forEach((card) => grid.appendChild(card));
    });

    if (key === 'company') {
      const wrap = document.getElementById('company-sections');
      if (!wrap) return;
      const sections = Array.from(wrap.querySelectorAll('.section'));
      sections.sort((a, b) => {
        const av = (a.dataset.company || '').toLowerCase();
        const bv = (b.dataset.company || '').toLowerCase();
        if (av < bv) return -1;
        if (av > bv) return 1;
        return 0;
      });
      sections.forEach((section) => wrap.appendChild(section));
    }
  }

  const cardSort = document.getElementById('card-sort');
  if (cardSort) {
    cardSort.addEventListener('change', () => {
      const [key, type] = cardSort.value.split(':');
      sortCards(key, type || 'text');
    });
  }

  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.btn-action');
    if (!btn) return;
    const container = btn.closest('.job-actions');
    if (!container) return;
    const action = btn.dataset.action;
    if (action === 'copy') { copyJob(container); return; }
    postStatus(container, action);
  });

  document.querySelectorAll('.job-actions').forEach((actions) => {
    applyCardState(actions.closest('.job-card') || actions.closest('tr') || actions, actions.dataset.status || 'none');
  });

  function initReportsUI() {
    window.__activeBoardFilter = 'all';
    initStatTiles();
    initTableSort();
    initFilters();
    initJobsApi();
    initSearchApi();
    initScrapeIndex();
    initCompanyLinks();
    initCompanyIndex();
    initCompanyHash();
    initJobHash();
    checkHealth();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReportsUI);
  } else {
    initReportsUI();
  }
})();
</script>"""


def _job_actions_html(job, compact=False):
    """Action buttons: open, apply, skip, interview, copy."""
    job_id = job.get("id") or ""
    ext_id = job.get("external_id") or job.get("job_key") or job.get("job_id") or ""
    board = job.get("board") or "indeed"
    url = job.get("url")
    app_status = job.get("application_status") or "none"
    is_applied = app_status == "applied"
    apply_label = "Applied" if is_applied else "Apply"
    apply_cls = "btn btn-action btn-apply is-done" if is_applied else "btn btn-action btn-apply"
    apply_disabled = " disabled" if is_applied else ""

    open_btn = ""
    if url and url not in ("Not Available", ""):
        open_btn = (
            f'<a class="btn btn-open" href="{_esc(url)}" target="_blank" rel="noopener">'
            f'{_esc(_open_board_label(board))}</a>'
        )

    status_line = "" if compact else '<div class="status-line"></div>'
    compact_cls = " job-actions-compact" if compact else ""

    return f"""
<div class="job-actions{compact_cls}" data-job-id="{_esc(str(job_id))}" data-external-id="{_esc(str(ext_id))}"
     data-board="{_esc(board)}" data-status="{_esc(app_status)}">
  {open_btn}
  <button type="button" class="{apply_cls}" data-action="applied"{apply_disabled}>{apply_label}</button>
  <button type="button" class="btn btn-action" data-action="skipped">Skip</button>
  <button type="button" class="btn btn-action" data-action="interviewing">Interview</button>
  <button type="button" class="btn btn-action btn-ghost" data-action="copy">Copy</button>
</div>
{status_line}"""


def _job_status_badge(job, in_db=True):
    flags = job.get("flags") or []
    app_st = job.get("application_status") or "none"
    if app_st == "applied":
        return _badge("applied", "user-applied")
    if app_st == "offer":
        return _badge("offer", "applied")
    if app_st in ("skipped", "rejected", "interviewing"):
        return _badge(app_st, "applied")
    if "ghost_candidate" in flags:
        return _badge("ghost?", "ghost")
    if "repost" in flags or (job.get("seen_count", 1) or 1) > 1:
        return _badge("seen before", "known")
    if job.get("_json_only"):
        return _badge("json only", "new")
    if job.get("seen_count", 1) == 1:
        return _badge("new", "new")
    return _badge("known", "known")


STAT_KEYS = (
    "json_files",
    "json_job_count",
    "jobs",
    "companies",
    "clusters",
    "sightings",
    "ghost_candidates",
    "repost_clusters",
)

METRIC_TIPS = {
    "json_files": "Number of JSON scrape files in artifacts/json (excluding combined_*).",
    "json_job_count": "Total job rows across all JSON files (includes duplicates across runs).",
    "jobs": "Unique jobs stored in SQLite (deduplicated by board + external job id).",
    "companies": "Distinct employers seen in the database.",
    "clusters": "Groups of similar postings (same company + normalized title/location fingerprint).",
    "sightings": "Each time a job was seen during a scrape run (one row per appearance).",
    "ghost_candidates": "Clusters with ghost_score ≥ 2: ≥3 different job IDs for the same role and ≥5 total sightings — often reposted/ghost listings.",
    "repost_clusters": "Clusters flagged repost: same role appeared under ≥2 different Indeed job IDs.",
}


def _current_stats(ctx):
    db = ctx.get("db_summary") or {}
    return {
        "json_files": ctx.get("json_files", 0),
        "json_job_count": ctx.get("json_job_count", 0),
        "jobs": db.get("jobs", 0) if db.get("exists") else 0,
        "companies": db.get("companies", 0) if db.get("exists") else 0,
        "clusters": db.get("clusters", 0) if db.get("exists") else 0,
        "sightings": db.get("sightings", 0) if db.get("exists") else 0,
        "ghost_candidates": db.get("ghost_candidates", 0) if db.get("exists") else 0,
        "repost_clusters": db.get("repost_clusters", 0) if db.get("exists") else 0,
    }


def _load_stats_snapshot(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _stat_card(value, label, delta=None, tip=""):
    delta_html = ""
    card_cls = "card stat-card stat-tile"
    if delta is not None and delta != 0:
        sign = "+" if delta > 0 else ""
        dcls = "delta-up" if delta > 0 else "delta-down"
        delta_html = f' <span class="stat-delta {dcls}">{sign}{delta}</span>'
        card_cls += " stat-changed"
    hint = '<span class="stat-hint">Click for details</span>' if tip else ""
    return (
        f'<button type="button" class="{card_cls}" data-stat-label="{_esc(label)}" data-stat-tip="{_esc(tip)}">'
        f'<div class="num">{value}{delta_html}</div>'
        f'<div class="lbl">{_esc(label)}</div>{hint}</button>'
    )


def _stat_grid(tiles_html, panel_id="stat-info-panel"):
    return (
        f'<div class="stat-grid">{tiles_html}</div>'
        f'<div class="stat-info-panel" id="{panel_id}" role="region" aria-live="polite"></div>'
    )


def _aggregate_ghost_clusters_by_company(clusters, canonical_by_norm=None, limit=30):
    """Merge ghost clusters that share the same normalized company name."""
    canonical_by_norm = canonical_by_norm or {}
    groups = {}

    for cluster in clusters or []:
        name_norm = cluster.get("company_norm") or normalize_company(cluster.get("company"))
        if not name_norm:
            name_norm = normalize_company(cluster.get("company")) or "unknown"

        if name_norm not in groups:
            groups[name_norm] = {
                "company_norm": name_norm,
                "company": canonical_by_norm.get(name_norm) or cluster.get("company") or name_norm,
                "display_names": set(),
                "clusters": [],
                "job_count": 0,
                "total_seen": 0,
                "ghost_score": 0.0,
                "flags": set(),
                "locations": set(),
            }

        group = groups[name_norm]
        display = cluster.get("company")
        if display:
            group["display_names"].add(display)
        group["clusters"].append(cluster)
        group["job_count"] += int(cluster.get("job_count") or 0)
        group["total_seen"] += int(cluster.get("total_seen") or 0)
        group["ghost_score"] = max(group["ghost_score"], float(cluster.get("ghost_score") or 0))
        for flag in cluster.get("flags") or []:
            group["flags"].add(flag)
        location = cluster.get("location_norm")
        if location:
            group["locations"].add(location)

    result = []
    for name_norm, group in groups.items():
        if name_norm in canonical_by_norm:
            group["company"] = canonical_by_norm[name_norm]
        elif group["display_names"]:
            group["company"] = sorted(group["display_names"], key=len, reverse=True)[0]
        group["flags"] = sorted(group["flags"])
        group["locations"] = sorted(group["locations"], key=str.lower)
        group["cluster_count"] = len(group["clusters"])
        group["clusters"].sort(
            key=lambda c: (-float(c.get("ghost_score") or 0), -int(c.get("total_seen") or 0))
        )
        result.append(group)

    result.sort(
        key=lambda g: (-g["ghost_score"], -g["total_seen"], g["company"].lower())
    )
    return result[:limit]


def _flags_badges_html(flags):
    if not flags:
        return "—"
    badges = "".join(
        _badge(
            f,
            "repost" if f == "repost" else "ghost" if "ghost" in f else "neutral",
        )
        for f in flags
    )
    return f'<span class="ghost-flags-row">{badges}</span>'


def _render_ghost_cluster_subtable(clusters):
    rows = ""
    for cluster in clusters or []:
        rows += f"""<tr>
          <td class="ghost-sub-col-title" title="{_esc(cluster.get('title_norm') or '')}">{_esc(cluster.get('title_norm') or '—')}</td>
          <td class="ghost-sub-col-loc">{_esc(cluster.get('location_norm') or '—')}</td>
          <td class="ghost-sub-col-num">{cluster.get('job_count', 0)}</td>
          <td class="ghost-sub-col-num">{cluster.get('total_seen', 0)}</td>
          <td class="ghost-sub-col-score">{cluster.get('ghost_score', 0):.1f}</td>
          <td class="ghost-sub-col-flags ghost-flags-cell">{_flags_badges_html(cluster.get('flags') or [])}</td>
        </tr>"""
    return f"""
    <div class="ghost-subtable-wrap">
      <table class="inner-table ghost-subtable">
        <thead><tr>
          <th class="ghost-sub-col-title">Title</th>
          <th class="ghost-sub-col-loc">Location</th>
          <th class="ghost-sub-col-num">Job IDs</th>
          <th class="ghost-sub-col-num">Sightings</th>
          <th class="ghost-sub-col-score">Score</th>
          <th class="ghost-sub-col-flags">Flags</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _render_ghost_list(clusters, ghost_company_slugs=None, canonical_by_norm=None):
    if not clusters:
        return '<p class="meta">No ghost candidates in the database right now.</p>'

    grouped = _aggregate_ghost_clusters_by_company(
        clusters, canonical_by_norm=canonical_by_norm, limit=30
    )
    body_rows = []
    for idx, group in enumerate(grouped):
        is_ghost = _company_is_ghost(group.get("company"), ghost_slugs=ghost_company_slugs)
        locations = group.get("locations") or []
        if len(locations) <= 2:
            loc_text = ", ".join(locations) if locations else "—"
        else:
            loc_text = f"{', '.join(locations[:2])} (+{len(locations) - 2} more)"

        sub_clusters = group.get("clusters") or []
        count = group.get("cluster_count") or len(sub_clusters)
        top = sub_clusters[0] if sub_clusters else {}
        top_title = top.get("title_norm") or "—"
        panel_id = f"ghost-panel-{idx}"
        single = count <= 1

        if single:
            roles_cell = (
                f'<div class="ghost-roles-summary">'
                f'<span class="ghost-top-role" title="{_esc(top_title)}">{_esc(top_title)}</span>'
                f"</div>"
            )
            row_class = "ghost-index-row ghost-single"
            expand_title = _esc(group.get("company") or "")
        else:
            roles_cell = (
                f'<div class="ghost-roles-summary">'
                f'<span class="ghost-role-count">{count} roles</span>'
                f'<span class="ghost-top-role" title="{_esc(top_title)}">{_esc(top_title)}</span>'
                f"</div>"
            )
            row_class = "ghost-index-row"
            expand_title = f"Show {count} role clusters"

        company_cell = (
            f'<div class="ghost-company-cell">'
            f'<span class="ghost-expand-icon" aria-hidden="true"></span>'
            f'{_company_name_html(group.get("company"), link=True, is_ghost=is_ghost)}'
            f"</div>"
        )

        summary = f"""
<tr class="{row_class}" data-panel="{panel_id}" title="{expand_title}">
  <td class="ghost-col-company">{company_cell}</td>
  <td class="ghost-col-roles">{roles_cell}</td>
  <td class="ghost-col-loc">{_esc(loc_text)}</td>
  <td class="ghost-col-num">{group.get('job_count', 0)}</td>
  <td class="ghost-col-num">{group.get('total_seen', 0)}</td>
  <td class="ghost-col-score">{group.get('ghost_score', 0):.1f}</td>
  <td class="ghost-col-flags ghost-flags-cell">{_flags_badges_html(group.get('flags') or [])}</td>
</tr>"""
        body_rows.append(summary)

        if not single:
            body_rows.append(f"""
<tr id="{panel_id}" class="ghost-detail-row">
  <td colspan="7">
    {_render_ghost_cluster_subtable(sub_clusters)}
  </td>
</tr>""")

    return f"""
    <div class="ghost-list table-scroll">
      <table class="inner-table ghost-table">
        <thead><tr>
          <th class="ghost-col-company">Company</th>
          <th class="ghost-col-roles">Roles</th>
          <th class="ghost-col-loc">Locations</th>
          <th class="ghost-col-num">Job IDs</th>
          <th class="ghost-col-num">Sightings</th>
          <th class="ghost-col-score">Score</th>
          <th class="ghost-col-flags">Flags</th>
        </tr></thead>
        <tbody>{"".join(body_rows)}</tbody>
      </table>
    </div>"""


def _json_session_key(filename):
    m = re.search(r"_(\d{8})_(\d{6})\.json$", filename or "")
    return f"{m.group(1)}_{m.group(2)}" if m else ""


def _json_session_anchor(filename):
    return quote_plus(Path(filename or "").name)


def _normalize_query_slug(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _json_query_slug(filename, query=None):
    if query:
        slug = _normalize_query_slug(query)
        if slug:
            return slug
    name = Path(filename or "").stem
    for prefix in ("dice_data_", "glassdoor_data_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    m = re.search(r"_(\d{8}_\d{6})$", name)
    if m:
        name = name[: m.start()].strip("_")
    return _normalize_query_slug(name)


def _shot_query_slug(filename):
    stem = Path(filename or "").stem
    m = re.match(r"page_?\d+_(.+?)_\d{8}_\d{6}", stem, re.I)
    if not m:
        return ""
    return _normalize_query_slug(m.group(1).replace("__", " "))


def _query_slug_score(json_slug, shot_slug):
    if not json_slug or not shot_slug:
        return 0.0
    if json_slug == shot_slug:
        return 1.0
    return SequenceMatcher(None, json_slug, shot_slug).ratio()


def _query_slugs_match(json_slug, shot_slug):
    return _query_slug_score(json_slug, shot_slug) >= 0.88


def match_shots_for_artifact(art, shots):
    """Link screenshots to a JSON scrape by query slug, then closest session time."""
    json_slug = _json_query_slug(art.get("filename", ""), art.get("query"))
    json_key = _json_session_key(art.get("filename", ""))
    if not json_slug:
        return []

    scored = []
    for shot in shots or []:
        shot_slug = _shot_query_slug(shot.get("name", ""))
        score = _query_slug_score(json_slug, shot_slug)
        if score >= 0.88:
            scored.append((score, shot))
    if not scored:
        return []

    max_score = max(score for score, _ in scored)
    best = [shot for score, shot in scored if score >= max_score - 0.01]

    session_keys = {shot.get("session_key") for shot in best if shot.get("session_key")}
    if json_key and len(session_keys) > 1:

        def _session_distance(shot):
            shot_key = shot.get("session_key") or ""
            if not shot_key or len(shot_key) < 15 or len(json_key) < 15:
                return 999999
            if shot_key[:8] != json_key[:8]:
                return 999999
            return abs(int(shot_key[9:15]) - int(json_key[9:15]))

        min_dist = min(_session_distance(shot) for shot in best)
        if min_dist < 999999:
            best = [shot for shot in best if _session_distance(shot) == min_dist]

    best.sort(key=lambda item: (item["kind"], item["page_num"], item["name"]))
    return best


def _shot_session_key(path):
    matches = re.findall(r"(\d{8})_(\d{6})", Path(path).stem)
    if matches:
        d, t = matches[0]
        return f"{d}_{t}"
    return ""


def _shot_href(rel_path):
    return f"../screenshots/{str(rel_path).replace(chr(92), '/')}"


def _guess_query_from_shots(images):
    if not images:
        return "—"
    first = images[0].get("name") or ""
    m = re.match(r"page_?\d+_(.+?)_\d{8}_", first, re.I)
    if m:
        return m.group(1).replace("_", " ").strip()
    return first


def scan_screenshot_files(screenshots_dir=None):
    root = Path(screenshots_dir) if screenshots_dir else SCREENSHOTS_DIR
    files = []
    if not root.exists():
        return files

    for path in sorted(root.rglob("*.png"), key=lambda p: p.name.lower()):
        rel = path.relative_to(root)
        kind = rel.parts[0] if len(rel.parts) > 1 else "root"
        page_m = re.match(r"page_?(\d+)", path.stem, re.I)
        page_num = int(page_m.group(1)) if page_m else 999
        files.append(
            {
                "rel": str(rel).replace("\\", "/"),
                "kind": kind,
                "session_key": _shot_session_key(path),
                "page_num": page_num,
                "name": path.name,
            }
        )
    return files


def build_screenshot_catalog(artifacts, screenshots_dir=None):
    shots = scan_screenshot_files(screenshots_dir)
    shots_by_json = {}
    used_shot_names = set()
    sessions = []

    for art in artifacts:
        imgs = match_shots_for_artifact(art, shots)
        if imgs:
            shots_by_json[art["filename"]] = imgs
            for img in imgs:
                used_shot_names.add(img["name"])

        if not imgs and not art.get("filename"):
            continue

        sessions.append(
            {
                "session_key": _json_session_key(art.get("filename", "")) or art.get("filename", ""),
                "session_anchor": _json_session_anchor(art.get("filename", "")),
                "artifacts": [art],
                "primary": art,
                "images": imgs,
                "query": art.get("query") or _guess_query_from_shots(imgs) or "—",
                "location": (art.get("location") or "").strip() or "—",
                "board": art.get("board", "indeed"),
                "when": (
                    art.get("scraped_at_readable")
                    or art.get("scraped_at")
                    or art.get("mtime")
                    or _json_session_key(art.get("filename", "")).replace("_", " ")
                ),
                "jobs": art.get("total_jobs", 0),
                "linked": bool(imgs),
            }
        )

    orphan_by_key = {}
    for shot in shots:
        if shot["name"] in used_shot_names:
            continue
        key = shot.get("session_key") or "unknown"
        orphan_by_key.setdefault(key, []).append(shot)
    for key, images in orphan_by_key.items():
        images.sort(key=lambda item: (item["kind"], item["page_num"], item["name"]))
        sessions.append(
            {
                "session_key": key,
                "session_anchor": quote_plus(f"orphan-{key}"),
                "artifacts": [],
                "primary": None,
                "images": images,
                "query": _guess_query_from_shots(images),
                "location": "—",
                "board": "indeed",
                "when": key.replace("_", " "),
                "jobs": 0,
                "linked": False,
            }
        )

    sessions.sort(
        key=lambda item: (
            item.get("primary") is None,
            (item.get("primary") or {}).get("mtime") or item["session_key"],
        ),
        reverse=True,
    )

    linked_json = len(shots_by_json)
    return {
        "sessions": sessions,
        "shots_by_json": shots_by_json,
        "total_images": len(shots),
        "linked_json": linked_json,
        "orphan_sessions": sum(1 for s in sessions if not s["artifacts"]),
    }


def _render_shot_strip(images, max_thumbs=8):
    if not images:
        return ""
    items = []
    for img in images[:max_thumbs]:
        href = _shot_href(img["rel"])
        items.append(
            f'<a class="shot-strip-link" href="{_esc(href)}" target="_blank" rel="noopener">'
            f'<img class="shot-strip-thumb" src="{_esc(href)}" alt="{_esc(img["name"])}" loading="lazy"></a>'
        )
    extra = len(images) - max_thumbs
    more = f'<span class="shot-strip-more">+{extra} more</span>' if extra > 0 else ""
    return f'<div class="shot-strip">{"".join(items)}{more}</div>'


def _render_shot_gallery(images):
    if not images:
        return '<div class="empty">No screenshots for this session</div>'
    items = []
    for img in images:
        href = _shot_href(img["rel"])
        kind = img.get("kind") or "root"
        cap = img.get("name") or ""
        items.append(
            f'<a class="shot-gallery-thumb" href="{_esc(href)}" data-caption="{_esc(cap)}">'
            f'<img src="{_esc(href)}" alt="{_esc(cap)}" loading="lazy">'
            f'<div class="shot-gallery-cap"><span class="shot-kind-tag">{_esc(kind)}</span>{_esc(cap)}</div></a>'
        )
    return f'<div class="shot-gallery">{"".join(items)}</div>'


def _screenshots_lightbox_js():
    return """<script>
(function () {
  const dlg = document.getElementById('shot-lightbox');
  if (!dlg) return;
  const img = dlg.querySelector('img');
  const cap = dlg.querySelector('.shot-lightbox-cap');
  document.querySelectorAll('.shot-gallery-thumb').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      img.src = el.href;
      cap.textContent = el.dataset.caption || el.querySelector('img')?.alt || '';
      dlg.showModal();
    });
  });
  dlg.addEventListener('click', (e) => {
    if (e.target === dlg) dlg.close();
  });
})();
</script>"""


def build_report_context(json_dir=None, db_path=None, variants=None):
    artifacts = load_json_artifacts(json_dir)
    db_summary = get_db_summary(db_path)
    variant_set = set(variants or [])
    need_all_jobs = not variant_set or variant_set.intersection({"cards", "compare", "companies"})
    db_jobs = get_db_jobs(db_path=db_path) if db_summary.get("exists") and need_all_jobs else []
    db_companies = get_db_companies(db_path=db_path) if db_summary.get("exists") else []
    ghost_clusters = get_ghost_clusters(limit=200, db_path=db_path) if db_summary.get("exists") else []
    board_counts = get_db_board_counts(db_path) if db_summary.get("exists") else {
        "indeed": 0,
        "dice": 0,
        "glassdoor": 0,
    }
    company_canonical = {
        co["name_norm"]: co["display_name"]
        for co in (db_companies or [])
        if co.get("name_norm")
    }

    json_job_count = sum(a["total_jobs"] for a in artifacts)
    json_files = len(artifacts)

    db_by_external = {}
    for job in db_jobs:
        db_by_external[(job["board"], job["external_id"])] = job

    ghost_company_slugs = _build_ghost_company_slugs(
        ghost_clusters,
        db_jobs if need_all_jobs else [],
    )
    screenshot_catalog = build_screenshot_catalog(artifacts)

    return {
        "generated_at": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "artifacts": artifacts,
        "db_summary": db_summary,
        "db_jobs": db_jobs,
        "db_companies": db_companies,
        "ghost_clusters": ghost_clusters,
        "ghost_company_slugs": ghost_company_slugs,
        "company_canonical": company_canonical,
        "json_job_count": json_job_count,
        "json_files": json_files,
        "db_by_external": db_by_external,
        "screenshot_catalog": screenshot_catalog,
        "shots_by_json": screenshot_catalog.get("shots_by_json") or {},
        "board_counts": board_counts,
    }


def _json_job_rows(jobs, db_by_external=None, ghost_company_slugs=None, board="indeed"):
    rows = ""
    board = (board or "indeed").lower()
    for job in jobs:
        ext = job.get("job_key") or job.get("job_id") or ""
        db_job = None
        if db_by_external and ext:
            db_job = db_by_external.get((board, ext))

        action_job = {**job, **db_job, "board": board} if db_job else {**job, "board": board}
        url = job.get("url")
        if db_job:
            actions = _job_actions_html(action_job, compact=True)
        elif url and url not in (_NOT_AVAILABLE, ""):
            actions = (
                f'<a class="btn btn-open" href="{_esc(url)}" target="_blank" rel="noopener">'
                f'{_esc(_open_board_label(board))}</a>'
            )
        else:
            actions = ""

        rows += _render_job_table_row(
            job,
            db_job,
            show_db=True,
            show_key=True,
            show_board=True,
            board=board,
            actions_html=actions,
            ghost_company_slugs=ghost_company_slugs,
        )
    return rows


def _render_json_scrape_folds(artifacts, db_by_external=None, ghost_company_slugs=None, limit=None, shots_by_json=None):
    if not artifacts:
        return '<div class="empty">No JSON files found</div>'

    shown = artifacts if limit is None else artifacts[:limit]
    total = len(artifacts)
    shots_by_json = shots_by_json or {}
    body_rows = []
    for idx, art in enumerate(shown):
        query = art.get("query") or "—"
        when = art.get("scraped_at_readable") or art.get("scraped_at") or art.get("mtime", "")
        location = (art.get("location") or "").strip() or "—"
        panel_id = f"scrape-panel-{idx}"
        art_board = art.get("board", "indeed")
        session_anchor = _json_session_anchor(art.get("filename", ""))
        shots = shots_by_json.get(art.get("filename")) or []
        shots_link = ""
        shot_strip = ""
        if shots:
            shots_link = (
                f' · <a href="report_screenshots.html#session-{_esc(session_anchor)}">'
                f'{len(shots)} screenshot(s)</a>'
            )
            shot_strip = _render_shot_strip(shots)

        body_rows.append(f"""
<tr class="scrape-index-row" data-panel="{panel_id}" data-filename="{_esc(art['filename'])}" title="Expand jobs from {_esc(art['filename'])}">
  <td class="col-chevron"></td>
  <td class="col-board">{_board_badge(art_board)}</td>
  <td class="col-query"><span class="cell-clip">{_esc(query)}</span></td>
  <td class="col-location"><span class="cell-clip">{_esc(location)}</span></td>
  <td class="col-jobs">{art['total_jobs']}</td>
  <td class="col-when"><span class="cell-clip">{_esc(str(when))}</span></td>
  <td class="col-file"><span class="cell-clip">{_esc(art['filename'])}{(' · ' + str(len(shots)) + ' shots') if shots else ''}</span></td>
</tr>
<tr id="{panel_id}" class="scrape-detail-row">
  <td colspan="7">
    <div class="scrape-panel-inner">
      <p class="scrape-panel-head">
        <strong>{_esc(query)}</strong> · {_esc(location)} · {art['total_jobs']} jobs · {_esc(str(when))} ·
        <code>{_esc(art['filename'])}</code>{shots_link}
      </p>
      {shot_strip}
      <div class="scrape-lazy-body" data-filename="{_esc(art['filename'])}" data-loaded="0">
        <p class="meta">Click row to load jobs from this scrape.</p>
      </div>
    </div>
  </td>
</tr>""")

    return f"""
<div class="scrape-block">
  <p class="meta scrape-file-count">Showing all {total} scrape file(s), newest first.</p>
  <div class="scrape-list table-scroll">
    <table class="inner-table scrape-index-table">
      <thead><tr>
        <th class="col-chevron"></th>
        <th class="col-board">Source</th>
        <th class="col-query">Query</th>
        <th class="col-location">Location</th>
        <th class="col-jobs">Jobs</th>
        <th class="col-when">Scraped</th>
        <th class="col-file">File</th>
      </tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
  </div>
</div>"""


def render_dashboard(ctx):
    db = ctx["db_summary"]
    deltas = ctx.get("stats_deltas") or {}
    prev_at = ctx.get("stats_previous_at")
    delta_note = ""
    if prev_at:
        delta_note = f' <span class="meta">Changes since last report ({_esc(prev_at[:16].replace("T", " "))}) are highlighted.</span>'

    def _d(key):
        return deltas.get(key)

    db_panel = ""
    if db.get("exists"):
        db_panel = f"""
        {_stat_grid(
            ""
            + _stat_card(db['jobs'], 'Unique jobs in DB', _d('jobs'), METRIC_TIPS['jobs'])
            + _stat_card(db['companies'], 'Companies', _d('companies'), METRIC_TIPS['companies'])
            + _stat_card(db['clusters'], 'Posting clusters', _d('clusters'), METRIC_TIPS['clusters'])
            + _stat_card(db['sightings'], 'Sightings', _d('sightings'), METRIC_TIPS['sightings'])
            + _stat_card(db['ghost_candidates'], 'Ghost candidates', _d('ghost_candidates'), METRIC_TIPS['ghost_candidates'])
            + _stat_card(db['repost_clusters'], 'Repost clusters', _d('repost_clusters'), METRIC_TIPS['repost_clusters']),
            'stat-info-db',
        )}
        <p class="sub">Database: <code>{_esc(db['path'])}</code>{delta_note}</p>
        <details class="metrics-help">
          <summary>How metrics are calculated</summary>
          <ul style="margin:12px 0 0; padding-left:18px">
            <li><strong>Sightings</strong> — one row each time a job appears in a scrape JSON import.</li>
            <li><strong>Clusters</strong> — same employer + normalized title/location grouped together.</li>
            <li><strong>Repost</strong> — cluster has ≥2 different Indeed job IDs for the same role (+1.0 score).</li>
            <li><strong>High frequency</strong> — cluster seen ≥4 times total (+1.5 score).</li>
            <li><strong>Ghost candidate</strong> — ≥3 job IDs and ≥5 sightings (+2.0 score). Dashboard count = clusters with score ≥ 2.</li>
            <li><strong>Ghost table</strong> — one summary row per company; click the row to expand a role breakdown table.</li>
          </ul>
        </details>
        <div class="section" style="margin-top:20px">
          <h2 style="font-size:16px;margin-bottom:8px">Ghost candidate clusters</h2>
          {_render_ghost_list(ctx.get('ghost_clusters') or [], ctx.get("ghost_company_slugs"), ctx.get("company_canonical"))}
        </div>
        """
    else:
        db_panel = '<div class="empty">No SQLite database yet. Run import or scrape with DB enabled.</div>'

    json_folds = _render_json_scrape_folds(
        ctx["artifacts"],
        ctx.get("db_by_external"),
        ctx.get("ghost_company_slugs"),
        shots_by_json=ctx.get("shots_by_json"),
    )

    body = f"""
    <h1>Job Scrape Dashboard</h1>
    <p class="sub">Generated {_esc(ctx['generated_at'])} · click any stat card for an explanation</p>
    {_stat_grid(
        _stat_card(ctx['json_files'], 'JSON scrape files', _d('json_files'), METRIC_TIPS['json_files'])
        + _stat_card(ctx['json_job_count'], 'Jobs in JSON (raw rows)', _d('json_job_count'), METRIC_TIPS['json_job_count'])
        + _stat_card(db.get('jobs', 0) if db.get('exists') else '—', 'Unique jobs in DB', _d('jobs'), METRIC_TIPS['jobs']),
        'stat-info-top',
    )}
    <div class="section">
      <h2>SQLite store</h2>
      {db_panel}
    </div>
    <div class="section">
      <h2>JSON scrapes</h2>
      <p class="sub" style="margin-top:-8px">All scrape files from artifacts/json (newest first). Click a row to load its job table on demand.</p>
      {json_folds}
    </div>
    """
    return _shell(
        "Job Dashboard",
        body,
        nav_links=_nav(),
        layout_full=True,
        page_class="dashboard-page",
    )


def render_table(ctx):
    board_counts = ctx.get("board_counts") or {"indeed": 0, "dice": 0, "glassdoor": 0}
    total_jobs = ctx["db_summary"].get("jobs", 0) if ctx["db_summary"].get("exists") else 0

    body = f"""
    <div class="jobs-topbar">
      <div class="jobs-topbar-left">
        <h1>Jobs</h1>
      </div>
      <div class="jobs-filter-wrap">
        <div class="jobs-filter-group">
          <span class="jobs-filter-label">Status</span>
          <div class="filter-bar jobs-filter-bar jobs-api-status-bar" data-api-filter="1">
            <button type="button" class="filter-btn active" data-filter="all">All</button>
            <button type="button" class="filter-btn" data-filter="open">To review</button>
            <button type="button" class="filter-btn" data-filter="applied">Applied by you</button>
            <button type="button" class="filter-btn" data-filter="interview">Interviewing</button>
            <button type="button" class="filter-btn" data-filter="skipped">Skipped</button>
            <button type="button" class="filter-btn" data-filter="ghost">Ghost?</button>
          </div>
        </div>
        <div class="jobs-filter-group">
          <span class="jobs-filter-label">Source</span>
          <div class="filter-bar jobs-board-filter-bar jobs-api-board-bar" data-api-filter="1">
            <button type="button" class="filter-btn active" data-board-filter="all">All sources</button>
            <button type="button" class="filter-btn" data-board-filter="indeed">Indeed ({board_counts['indeed']})</button>
            <button type="button" class="filter-btn" data-board-filter="dice">Dice ({board_counts['dice']})</button>
            <button type="button" class="filter-btn" data-board-filter="glassdoor">Glassdoor ({board_counts['glassdoor']})</button>
          </div>
        </div>
      </div>
    </div>
    <p class="sub"><span id="jobs-result-count">{total_jobs} listings</span> · Indeed {board_counts['indeed']} · Dice {board_counts['dice']} · Glassdoor {board_counts['glassdoor']} · {_esc(ctx['generated_at'])} · loaded from API (50 per page)</p>
    <div class="jobs-pagination">
      <button type="button" class="filter-btn" id="jobs-prev" disabled>Previous</button>
      <span id="jobs-page-info" class="meta">Loading…</span>
      <button type="button" class="filter-btn" id="jobs-next">Next</button>
    </div>
    <div class="panel jobs-table-panel">
      <div class="table-scroll">
      <table id="jobs-table" class="inner-table sortable-table actions-table" data-api-load="1">
        <thead>{_job_table_head(include_status=True, include_board=True, include_seen=True)}</thead>
        <tbody><tr><td colspan="12" class="empty">Loading…</td></tr></tbody>
      </table>
      </div>
    </div>
    """
    return _shell(
        "Jobs",
        body,
        nav_links=_nav(),
        layout_full=True,
        page_class="jobs-page",
    )


def render_search(ctx):
    board_counts = ctx.get("board_counts") or {"indeed": 0, "dice": 0, "glassdoor": 0}
    total_jobs = ctx["db_summary"].get("jobs", 0) if ctx["db_summary"].get("exists") else 0

    body = f"""
    <div class="search-topbar">
      <h1>Search</h1>
      <div class="search-controls">
        <div class="search-input-wrap">
          <input id="search-query" class="search-input" type="search"
                 placeholder="Company or job title…" autocomplete="off" spellcheck="false">
        </div>
        <div class="search-mode-group">
          <span class="search-mode-label">Match</span>
          <div class="filter-bar search-mode-bar" data-api-filter="1">
            <button type="button" class="filter-btn" data-search-mode="company">Company</button>
            <button type="button" class="filter-btn" data-search-mode="title">Title</button>
            <button type="button" class="filter-btn active" data-search-mode="both">Both</button>
          </div>
        </div>
        <div class="search-mode-group">
          <span class="search-mode-label">Source</span>
          <div class="filter-bar search-board-bar" data-api-filter="1">
            <button type="button" class="filter-btn active" data-board-filter="all">All</button>
            <button type="button" class="filter-btn" data-board-filter="indeed">Indeed ({board_counts['indeed']})</button>
            <button type="button" class="filter-btn" data-board-filter="dice">Dice ({board_counts['dice']})</button>
            <button type="button" class="filter-btn" data-board-filter="glassdoor">Glassdoor ({board_counts['glassdoor']})</button>
          </div>
        </div>
      </div>
    </div>
    <p class="sub"><span id="search-result-count" class="search-result-count">Type to search, or pick a source to browse</span> · {_esc(ctx['generated_at'])} · server-side search</p>
    <div class="jobs-pagination search-pagination">
      <button type="button" class="filter-btn" id="search-prev" disabled>Previous</button>
      <span id="search-page-info" class="meta"></span>
      <button type="button" class="filter-btn" id="search-next" disabled>Next</button>
    </div>
    <div class="panel search-table-panel">
      <div class="table-scroll">
      <table id="search-table" class="inner-table sortable-table actions-table" data-api-load="1">
        <thead>{_job_table_head(include_status=True, include_board=True, include_seen=True)}</thead>
        <tbody><tr><td colspan="12" class="empty">Enter a company or job title, or pick a source to browse.</td></tr></tbody>
      </table>
      </div>
    </div>
    """
    return _shell(
        "Search",
        body,
        nav_links=_nav(),
        layout_full=True,
        page_class="search-page",
    )


def render_cards(ctx):
    by_company = {}
    ghost_slugs = ctx.get("ghost_company_slugs")
    for job in ctx["db_jobs"]:
        key = job.get("company_display") or job.get("company") or "Unknown"
        by_company.setdefault(key, []).append(job)

    sections = ""
    for company, jobs in sorted(by_company.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:60]:
        is_ghost = _company_is_ghost(company, ghost_slugs=ghost_slugs) or any(
            "ghost_candidate" in (j.get("flags") or []) for j in jobs
        )
        cards = ""
        for job in jobs[:12]:
            status = _job_status_badge(job)
            app_st = job.get("application_status") or "none"
            position = _clean_field(job.get("search_query")) or "—"
            posted = _posted_display(_job_posted_raw(job))
            scraped_display, _ = _scraped_display(job)
            sort_attrs = _job_sort_attrs(job)
            cards += f"""
            <div class="job-card" {sort_attrs} data-application-status="{_esc(app_st)}"
                 data-job-id="{_esc(str(job.get('id','')))}" data-external-id="{_esc(str(job.get('external_id','')))}">
              <h3>{_esc(job.get('title'))}</h3>
              <div class="meta">{_board_badge(job.get('board', 'indeed'))} {status}<br>{_company_name_html(company, is_ghost=is_ghost)} · {_esc(position)}<br>
              {_esc(job.get('location'))} · {_esc(job.get('salary') or '—')}<br>
              Posted {_esc(posted)} · scraped {_esc(scraped_display)} · seen {job.get('seen_count', 1)}×</div>
              {_job_actions_html(job)}
            </div>"""
        sections += f"""
        <div class="section" data-company="{_esc(company.lower())}">
          <h2>{_company_name_html(company, link=True, is_ghost=is_ghost)} <span class="sub">({len(jobs)} listings)</span></h2>
          <div class="cards-grid">{cards}</div>
        </div>"""

    if not sections:
        sections = '<div class="empty">No jobs in database yet.</div>'

    body = f"""
    <div class="cards-topbar">
      <h1>Jobs by Company</h1>
      <div class="filter-bar cards-filter-bar" data-filter-target="#company-sections .job-card[data-application-status]">
        <button type="button" class="filter-btn active" data-filter="all">All</button>
        <button type="button" class="filter-btn" data-filter="open">To review</button>
        <button type="button" class="filter-btn" data-filter="applied">Applied by you</button>
        <button type="button" class="filter-btn" data-filter="interview">Interviewing</button>
        <button type="button" class="filter-btn" data-filter="skipped">Skipped</button>
      </div>
    </div>
    <p class="sub">Grouped by employer · {_esc(ctx['generated_at'])} · <strong>Applied</strong> means you clicked Apply here (not from Indeed).</p>
    <div class="card-sort-bar">
      <label for="card-sort">Sort cards by</label>
      <select id="card-sort" class="card-sort-select">
        <option value="company:text">Company</option>
        <option value="position:text">Position type</option>
        <option value="title:text">Job title</option>
        <option value="salary:num">Salary</option>
        <option value="postedRank:num">Posted (newest first)</option>
        <option value="scraped:date">Date scraped</option>
      </select>
    </div>
    <div id="company-sections">{sections}</div>
    """
    return _shell(
        "Jobs by Company",
        body,
        nav_links=_nav(),
        layout_full=True,
        page_class="cards-page",
    )


def render_compare(ctx):
    latest = ctx["artifacts"][0] if ctx["artifacts"] else None
    db_by_external = ctx.get("db_by_external") or {}
    ghost_slugs = ctx.get("ghost_company_slugs")

    ghost_slugs = ctx.get("ghost_company_slugs")

    json_table = '<div class="empty">No JSON files</div>'
    latest_board = "indeed"
    if latest:
        latest_board = latest.get("board", "indeed")
        json_rows = _json_job_rows(latest["jobs"], db_by_external, ghost_slugs, latest_board)
        json_table = f"""
        <div class="table-scroll">
        <table class="inner-table sortable-table actions-table">
          <thead>{_job_table_head(include_db=True, include_key=True, include_board=True)}</thead>
          <tbody>{json_rows or '<tr><td colspan="11" class="empty">No jobs in file</td></tr>'}</tbody>
        </table>
        </div>"""

    db_rows = ""
    for job in ctx["db_jobs"][:80]:
        db_rows += _render_job_table_row(
            job,
            show_status=True,
            show_board=True,
            show_seen=True,
            show_key=True,
            actions_html=_job_actions_html(job, compact=True),
            company_link_target="jobs",
            ghost_company_slugs=ghost_slugs,
        )

    if not db_rows:
        db_rows = '<tr><td colspan="13" class="empty">Database empty</td></tr>'

    latest_label = latest["filename"] if latest else "none"
    latest_query = (latest or {}).get("query") or "—"
    latest_count = (latest or {}).get("total_jobs") or 0
    latest_board_label = _board_label(latest_board if latest else "indeed")

    body = f"""
    <h1>JSON vs Database Compare</h1>
    <p class="sub">Latest scrape: <code>{_esc(latest_label)}</code> · {_board_badge(latest_board if latest else 'indeed')} · {_esc(latest_query)} · {latest_count} jobs · {_esc(ctx['generated_at'])}</p>
    <div class="compare-split">
      <div class="compare-panel">
        <h2>Latest JSON scrape ({_esc(latest_board_label)})</h2>
        <p class="sub">Jobs from the most recent JSON file — actions when row is in DB.</p>
        {json_table}
      </div>
      <div class="compare-panel">
        <h2>SQLite (recent, all sources)</h2>
        <p class="sub">Same jobs in the database with full action buttons. Source column shows Indeed, Dice, or Glassdoor.</p>
        <div class="table-scroll">
        <table class="inner-table sortable-table actions-table">
          <thead>{_job_table_head(include_status=True, include_board=True, include_seen=True, include_key=True)}</thead>
          <tbody>{db_rows}</tbody>
        </table>
        </div>
      </div>
    </div>
    <div class="section">
      <h2>Summary</h2>
      <div class="grid">
        <div class="card"><div class="num">{ctx['json_files']}</div><div class="lbl">JSON files</div></div>
        <div class="card"><div class="num">{ctx['json_job_count']}</div><div class="lbl">JSON job rows</div></div>
        <div class="card"><div class="num">{ctx['db_summary'].get('jobs', 0)}</div><div class="lbl">DB unique jobs</div></div>
        <div class="card"><div class="num">{ctx['db_summary'].get('sightings', 0)}</div><div class="lbl">DB sightings</div></div>
      </div>
    </div>
    """
    return _shell(
        "JSON vs DB Compare",
        body,
        nav_links=_nav(),
        layout_full=True,
        page_class="compare-page",
    )


def _google_link(name):
    return f"https://www.google.com/search?q={quote_plus(f'{name} company careers')}"


def _indeed_company_link(name):
    return f"https://www.indeed.com/jobs?q={quote_plus(name or '')}"


def build_company_profiles(jobs):
    profiles = {}
    for job in jobs:
        name = job.get("company_display") or job.get("company") or "Unknown"
        slug = _company_slug(name)
        if slug not in profiles:
            profiles[slug] = {
                "name": name,
                "slug": slug,
                "jobs": [],
                "urls": [],
                "locations": set(),
                "positions": set(),
            }
        profile = profiles[slug]
        profile["jobs"].append(job)
        loc = _clean_field(job.get("location"))
        if loc:
            profile["locations"].add(loc)
        pos = _clean_field(job.get("search_query"))
        if pos:
            profile["positions"].add(pos)
        url = _clean_field(job.get("url"))
        if url and url not in profile["urls"]:
            profile["urls"].append(url)
    for profile in profiles.values():
        profile["locations"] = sorted(profile["locations"])
        profile["positions"] = sorted(profile["positions"])
        profile["job_count"] = len(profile["jobs"])
    return sorted(profiles.values(), key=lambda x: (-x["job_count"], x["name"].lower()))


def _render_company_detail(profile):
    job_rows = ""
    for job in profile["jobs"][:40]:
        url = _clean_field(job.get("url"))
        title = job.get("title") or "Job"
        loc = _clean_field(job.get("location")) or "—"
        pos = _clean_field(job.get("search_query")) or "—"
        posted = _posted_display(_job_posted_raw(job))
        if url:
            title_cell = f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(title)}</a>'
        else:
            title_cell = _esc(title)
        job_rows += f"""<tr>
          <td class="col-title">{title_cell}</td>
          <td class="meta">{_esc(pos)}</td>
          <td class="meta">{_esc(loc)}</td>
          <td class="meta">{_esc(posted)}</td>
        </tr>"""
    if len(profile["jobs"]) > 40:
        job_rows += f'<tr><td colspan="4" class="meta">+ {len(profile["jobs"]) - 40} more listings in database</td></tr>'

    return f"""
    <div class="company-panel-inner">
      <div class="company-links">
        <a class="company-link-google" href="{_google_link(profile['name'])}" target="_blank" rel="noopener">Lookup in Google</a>
        <a class="company-link-indeed" href="{_indeed_company_link(profile['name'])}" target="_blank" rel="noopener">Indeed search</a>
      </div>
      <p class="company-panel-meta">
        <strong>{profile['job_count']}</strong> scraped listing(s) ·
        Positions: {_esc(', '.join(profile['positions'][:8]) or '—')}
        {f' (+{len(profile["positions"]) - 8} more)' if len(profile['positions']) > 8 else ''} ·
        Locations: {_esc(', '.join(profile['locations'][:8]) or '—')}
        {f' (+{len(profile["locations"]) - 8} more)' if len(profile['locations']) > 8 else ''}
      </p>
      <div class="table-scroll">
        <table class="inner-table company-job-table">
          <thead><tr><th>Title</th><th>Position</th><th>Location</th><th>Posted</th></tr></thead>
          <tbody>{job_rows or '<tr><td colspan="4" class="empty">No jobs stored</td></tr>'}</tbody>
        </table>
      </div>
    </div>"""


def _render_companies_table(profiles, ghost_company_slugs=None, limit=None):
    if not profiles:
        return '<div class="empty">No companies in database</div>'

    shown = profiles if limit is None else profiles[:limit]
    total = len(profiles)
    body_rows = []
    for idx, profile in enumerate(shown):
        panel_id = f"company-panel-{idx}"
        loc_preview = ", ".join(profile["locations"][:2]) or "—"
        if len(profile["locations"]) > 2:
            loc_preview += f" (+{len(profile['locations']) - 2})"
        pos_preview = ", ".join(profile["positions"][:2]) or "—"
        if len(profile["positions"]) > 2:
            pos_preview += f" (+{len(profile['positions']) - 2})"
        is_ghost = _company_is_ghost(profile["name"], ghost_slugs=ghost_company_slugs)

        body_rows.append(f"""
<tr class="company-index-row" id="{profile['slug']}" data-company-slug="{profile['slug']}" data-panel="{panel_id}" title="Expand {_esc(profile['name'])}">
  <td class="col-chevron"></td>
  <td>{_company_name_html(profile['name'], link=False, is_ghost=is_ghost)}</td>
  <td class="col-jobs">{profile['job_count']}</td>
  <td class="col-loc meta"><span class="cell-clip">{_esc(loc_preview)}</span></td>
  <td class="col-pos meta"><span class="cell-clip">{_esc(pos_preview)}</span></td>
</tr>
<tr id="{panel_id}" class="company-detail-row">
  <td colspan="5">{_render_company_detail(profile)}</td>
</tr>""")

    count_note = f"Showing all {total} employers with jobs in the database."
    if limit is not None and total > len(shown):
        count_note = f"Showing {len(shown)} of {total} employers (sorted by job count)."

    return f"""
<div class="panel">
  <p class="meta">{count_note}</p>
  <div class="table-scroll">
    <table class="inner-table scrape-index-table company-index-table">
      <thead><tr>
        <th class="col-chevron"></th>
        <th>Company</th>
        <th class="col-jobs">Jobs</th>
        <th class="col-loc">Locations</th>
        <th class="col-pos">Positions searched</th>
      </tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
  </div>
</div>"""


def render_companies(ctx):
    profiles = build_company_profiles(ctx["db_jobs"])
    table = _render_companies_table(profiles, ctx.get("ghost_company_slugs"))
    db_co_total = ctx["db_summary"].get("companies", len(profiles))

    body = f"""
    <h1>Companies</h1>
    <p class="sub">{len(profiles)} employers with listings · {db_co_total} company rows in DB · {_esc(ctx['generated_at'])} · click a row to expand listings and lookup links</p>
    {table}
    """
    return _shell(
        "Companies",
        body,
        nav_links=_nav(),
        layout_full=True,
        page_class="companies-page",
    )


def _cmd_block(label, command):
    return f"""<div class="cmd-block">
  <span class="cmd-label">{_esc(label)}</span>
  <code>{_esc(command)}</code>
</div>"""


def _index_guide_html(ctx):
    root = PROJECT_ROOT
    db = ctx["db_summary"]
    db_path = default_db_path()
    json_dir = root / "artifacts" / "json"
    html_dir = HTML_DIR
    job_count = db.get("jobs", 0) if db.get("exists") else 0
    app_count = db.get("applications", 0) if db.get("exists") else 0

    flow = """Chrome (debug port) or Docker (Xvfb + Chromium)
    │
    ▼
maintance/run_*_attach.sh  ──►  src/main.py  ──►  modules/scraper_*.py
    │                                    │
    └────────────────────────────────────┘
                       ▼
         artifacts/json/<query>_<timestamp>.json
                       │
         ┌─────────────┴───────────────┐
         ▼                             ▼
 modules/job_store.py          JSON read at build time
 import_all_json / upsert              │
         │                             │
         ▼                             │
    artifacts/jobs.db ◄────────────────┘
         │
         ▼
 modules/job_report_html.py  ──►  artifacts/html/*.html (shells + static pages)
         │
         ▼ (generate_job_reports.py --serve)
 modules/job_report_api.py   ◄──  /api/jobs, /api/scrapes/…, Apply/Skip, /screenshots/*"""

    sections = []

    sections.append(f"""
<details class="readme-section">
  <summary>Data flow — how a scrape becomes a report</summary>
  <div class="readme-body">
    <p>Each run writes raw JSON, merges into SQLite for cross-run history, then HTML shells are built. Jobs, Search, and lazy Dashboard panels load data from the FastAPI server when you use <code>--serve</code> (or Docker <code>report-server</code>).</p>
    {_data_flow_mermaid_html(flow)}
    <p><strong>Right now:</strong> {ctx['json_files']} JSON file(s) in <span class="file-tag">artifacts/json/</span> · {job_count} job(s) in DB · {app_count} application record(s).</p>
  </div>
</details>""")

    sections.append(f"""
<details class="readme-section">
  <summary>1 · Data collection (scrape)</summary>
  <div class="readme-body">
    <p><strong>What happens:</strong> Attach scripts warm Chrome (or Docker runs headless Chromium), then <span class="file-tag">src/main.py</span> drives the board scraper. Results land as one JSON file per search query.</p>
    <ul>
      <li><span class="file-tag">config/job_titles.ini</span> — default queries for auto mode</li>
      <li><span class="file-tag">artifacts/chrome_profile/</span> — persistent browser session</li>
      <li><span class="file-tag">artifacts/json/</span> — scrape output (<code>devops_engineer_20260621_215329.json</code> style names)</li>
    </ul>
    {_cmd_block("Per-board attach scripts", f"bash maintance/run_indeed_attach.sh\nbash maintance/run_glassdoor_attach.sh\nbash maintance/run_dice_attach.sh")}
    {_cmd_block("Menu / run all", f"bash maintance/run_scraper_attach.sh")}
    {_cmd_block("Glassdoor only", f"bash maintance/run_glassdoor_attach.sh")}
    {_cmd_block("Interactive scrape (prompts for board / query)", f"cd {root}\npython3 src/main.py")}
    {_cmd_block("Auto scrape one query to JSON", f"cd {root}\npython3 src/main.py --auto --board indeed --query \"devops engineer\" --location remote --max 50")}
  </div>
</details>""")

    sections.append(f"""
<details class="readme-section">
  <summary>2 · Processing (JSON artifacts)</summary>
  <div class="readme-body">
    <p><strong>What happens:</strong> Each JSON file holds one scrape run — metadata plus a <code>jobs[]</code> array. Reports read these files directly for Dashboard tabs and Compare view; they are the source of truth for <em>this run</em>.</p>
    <ul>
      <li><span class="file-tag">artifacts/json/*.json</span> — per-query scrape files</li>
      <li><span class="file-tag">artifacts/json/combined_*.json</span> — multi-query runs (skipped on DB import)</li>
    </ul>
    {_cmd_block("List recent scrape files", f"ls -lt {json_dir}/*.json | head")}
    {_cmd_block("Peek at one file (jobs count + query)", f'python3 -c "import json; d=json.load(open(\'{json_dir}/FILE.json\')); print(d.get(\'metadata\',{{}})); print(len(d.get(\'jobs\',[])),\'jobs\')"')}
    <p>Open <a href="report_dashboard.html">Dashboard</a> → click a scrape row to expand that file's jobs. <a href="report_compare.html">Compare</a> shows latest JSON rows vs DB matches.</p>
  </div>
</details>""")

    sections.append(f"""
<details class="readme-section">
  <summary>3 · Aggregation (SQLite)</summary>
  <div class="readme-body">
    <p><strong>What happens:</strong> <span class="file-tag">modules/job_store.py</span> deduplicates jobs by board + external id, tracks sightings per scrape, clusters reposts, and scores ghost candidates.</p>
    <ul>
      <li><span class="file-tag">artifacts/jobs.db</span> — SQLite database</li>
      <li>Tables: <code>jobs</code>, <code>sightings</code>, <code>posting_clusters</code>, <code>companies</code>, <code>applications</code></li>
      <li><span class="file-tag">artifacts/html/stats_snapshot.json</span> — previous run counts for dashboard deltas</li>
    </ul>
    {_cmd_block("Import all JSON into DB (skips combined_*)", f"cd {root}\npython3 modules/generate_job_reports.py --import-json")}
    {_cmd_block("Import + rebuild HTML", f"cd {root}\npython3 modules/generate_job_reports.py --import-json --variants index,dashboard,table,search,companies,cards,screenshots,compare")}
    {_cmd_block("Custom paths", f"python3 modules/generate_job_reports.py --import-json --json-dir {json_dir} --db {db_path} --out {html_dir}")}
  </div>
</details>""")

    sections.append("""
<details class="readme-section">
  <summary>4 · Applied vs not applied</summary>
  <div class="readme-body">
    <p><strong>Important:</strong> <em>Applied</em> in these reports means <strong>you clicked Apply in the HTML UI</strong> — not Indeed's own "Applied" badge. Status is stored in the <code>applications</code> table (one row per posting cluster).</p>
    <ul>
      <li><strong>applied</strong> — marked via Apply button (requires server)</li>
      <li><strong>skipped</strong> / <strong>interviewing</strong> — other actions on Cards page</li>
      <li><strong>not in DB</strong> — job seen in JSON only, not imported yet</li>
      <li><strong>in DB, no application</strong> — tracked listing, no action taken</li>
    </ul>
    <p>Filters on Jobs / Cards: <em>To review</em> = no application · <em>Applied by you</em> = strict <code>applied</code> status only.</p>
  </div>
</details>""")

    sections.append(f"""
<details class="readme-section">
  <summary>5 · View reports &amp; SQLite</summary>
  <div class="readme-body">
    <p><strong>Static HTML</strong> — Dashboard, Companies, Compare, Screenshots open from disk. Jobs and Search need the API server.</p>
    {_cmd_block("Open index in browser (macOS)", f"open {html_dir}/index.html")}
    {_cmd_block("Regenerate all report pages", f"cd {root}\npython3 modules/generate_job_reports.py")}
    <p><strong>Interactive mode</strong> — FastAPI serves HTML + REST on port 8765 (Jobs/Search pagination, lazy dashboard JSON, Apply/Skip).</p>
    {_cmd_block("Serve reports (no rebuild)", f"cd {root}\npython3 modules/generate_job_reports.py --serve")}
    {_cmd_block("Rebuild then serve", f"cd {root}\npython3 modules/generate_job_reports.py --serve --regenerate")}
    {_cmd_block("Docker (same behavior)", f"cd {root}/build\n./build.sh reports && ./build.sh serve\n# open http://localhost:8765/")}
    <p>Then use <a href="http://127.0.0.1:8765/report_cards.html">http://127.0.0.1:8765/report_cards.html</a> for Apply/Skip actions.</p>
    <p><strong>SQLite CLI</strong></p>
    {_cmd_block("Job + application counts", f'sqlite3 {db_path} "SELECT (SELECT COUNT(*) FROM jobs) AS jobs, (SELECT COUNT(*) FROM applications) AS apps;"')}
    {_cmd_block("Your applied listings", f"sqlite3 {db_path} \"SELECT j.title, j.company, a.status FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.status='applied' LIMIT 20;\"")}
    {_cmd_block("Open DB in GUI", f"open {db_path}   # macOS opens TablePlus/SQLite viewer if installed")}
  </div>
</details>""")

    sections.append(f"""
<details class="readme-section">
  <summary>6 · CLI cheat sheet (files involved)</summary>
  <div class="readme-body">
    <table class="inner-table" style="min-width:0;font-size:11px">
      <thead><tr><th>Task</th><th>Command</th><th>Key files</th></tr></thead>
      <tbody>
        <tr><td>Scrape orchestrator</td><td><code>bash maintance/run_scraper_attach.sh</code></td><td class="meta">Menu launcher · or run_indeed_attach.sh / run_glassdoor_attach.sh / run_dice_attach.sh</td></tr>
        <tr><td>Scraper entry</td><td><code>python3 src/main.py --auto …</code></td><td class="meta">src/main.py, modules/scraper_indeed.py</td></tr>
        <tr><td>Build reports</td><td><code>python3 modules/generate_job_reports.py</code></td><td class="meta">modules/generate_job_reports.py, modules/job_report_html.py</td></tr>
        <tr><td>Import JSON → DB</td><td><code>python3 modules/generate_job_reports.py --import-json</code></td><td class="meta">modules/job_store.py, artifacts/jobs.db</td></tr>
        <tr><td>Interactive API</td><td><code>python3 modules/generate_job_reports.py --serve</code></td><td class="meta">modules/job_report_api.py, modules/job_report_server.py</td></tr>
        <tr><td>Docker reports</td><td><code>cd build && ./build.sh reports && ./build.sh serve</code></td><td class="meta">build/docker-compose.yml → report-server</td></tr>
        <tr><td>UI prototypes</td><td><code>python3 modules/generate_job_reports.py --prototypes</code></td><td class="meta">modules/job_report_prototypes.py, artifacts/html/prototypes/</td></tr>
        <tr><td>Chrome cache cleanup</td><td><code>bash maintance/chrome_cache_cleanup.sh -d</code></td><td class="meta">maintance/chrome_cache_cleanup.sh</td></tr>
      </tbody>
    </table>
    {_cmd_block("Rebuild one variant only", f"cd {root}\npython3 modules/generate_job_reports.py --variants dashboard,table")}
  </div>
</details>""")

    return f"""
<div class="readme-block">
  <h2>Read me &amp; cheat sheet</h2>
  <p class="sub" style="margin-top:0">Expand a topic below — data collection, processing, aggregation, applied status, and CLIs.</p>
  {''.join(sections)}
</div>"""


def render_screenshots(ctx):
    catalog = ctx.get("screenshot_catalog") or {}
    sessions = catalog.get("sessions") or []
    sections = []
    for sess in sessions:
        arts = sess.get("artifacts") or []
        json_names = ", ".join(art.get("filename", "") for art in arts)
        board = sess.get("board", "indeed")
        orphan_note = ""
        if not arts:
            orphan_note = ' · <span class="meta">No matching JSON file</span>'
        elif not sess.get("images"):
            orphan_note = ' · <span class="meta">JSON only — no page captures</span>'

        anchor = sess.get("session_anchor") or quote_plus(str(sess.get("session_key", "")))
        sections.append(f"""
<section class="shot-session" id="session-{_esc(anchor)}">
  <div class="shot-session-head">
    <h3>{_esc(sess.get("query") or "—")}</h3>
    {_board_badge(board)}
    <span class="shot-session-meta">
      {_esc(str(sess.get("when") or ""))} · {_esc(sess.get("location") or "—")} ·
      {sess.get("jobs", 0)} jobs · {len(sess.get("images") or [])} image(s){orphan_note}
    </span>
  </div>
  {f'<p class="shot-session-meta"><code>{_esc(json_names)}</code></p>' if json_names else ''}
  {_render_shot_gallery(sess.get("images") or [])}
</section>""")

    body = f"""
    <h1>Screenshot catalog</h1>
    <p class="sub">Generated {_esc(ctx['generated_at'])} · page captures under <code>artifacts/screenshots/</code></p>
    <div class="screenshots-summary">
      <span>{catalog.get('total_images', 0)} PNG files</span>
      <span>{catalog.get('linked_json', 0)} JSON scrape(s) with captures</span>
      <span>{len(sessions)} session(s)</span>
      <span>{catalog.get('orphan_sessions', 0)} unlinked capture group(s)</span>
    </div>
    {''.join(sections) if sections else '<div class="empty">No screenshots found under artifacts/screenshots/</div>'}
    <dialog id="shot-lightbox">
      <img src="" alt="">
      <div class="shot-lightbox-cap"></div>
    </dialog>
    """
    return _shell("Screenshot catalog", body, nav_links=_nav(), interactive=False, layout_full=True, page_class="screenshots-page", extra_script=_screenshots_lightbox_js(),)


def render_index(ctx):
    cards = ""
    for name, desc, file in [
        ("Dashboard", "Stats + JSON scrape index", "report_dashboard.html"),
        ("Jobs", "Compact table — filter, sort, apply actions", "report_table.html"),
        ("Search", "Find jobs by company or title", "report_search.html"),
        ("Companies", "Employer directory + Indeed URLs", "report_companies.html"),
        ("Cards", "Grouped cards — filter by status", "report_cards.html"),
        ("Screenshots", "Page captures grouped by scrape session", "report_screenshots.html"),
        ("Compare", "Latest JSON vs database", "report_compare.html"),
    ]:
        cards += f"""
        <a class="card" href="{file}" style="text-decoration:none;color:inherit;display:block">
          <h3 style="margin:0 0 8px">{name}</h3>
          <p class="sub" style="margin:0">{desc}</p>
        </a>"""

    db = ctx["db_summary"]
    body = f"""
    <h1>Indeed Scraper Reports</h1>
    <p class="sub">Generated {_esc(ctx['generated_at'])} · {ctx['json_files']} JSON files · DB {'ready' if db.get('exists') and db.get('jobs') else 'empty'}</p>
    <div class="grid index-grid">{cards}</div>
    {_index_guide_html(ctx)}
    """
    return _shell("Scraper Reports", body, nav_links=_nav(), interactive=False, layout_full=True, mermaid=True, page_class="index-page",)


RENDERERS = {
    "dashboard": render_dashboard,
    "table": render_table,
    "search": render_search,
    "cards": render_cards,
    "compare": render_compare,
    "companies": render_companies,
    "screenshots": render_screenshots,
    "index": render_index,
}


def generate_reports(variants=None, json_dir=None, db_path=None, output_dir=None):
    output_dir = Path(output_dir) if output_dir else HTML_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    chosen = variants or list(RENDERERS.keys())

    ctx = build_report_context(json_dir=json_dir, db_path=db_path, variants=chosen)
    snapshot_path = output_dir / "stats_snapshot.json"
    previous = _load_stats_snapshot(snapshot_path)
    current = _current_stats(ctx)
    ctx["stats_deltas"] = {
        key: current[key] - previous[key]
        for key in STAT_KEYS
        if previous and key in previous and current.get(key) != previous.get(key)
    }
    ctx["stats_previous_at"] = previous.get("saved_at") if previous else None

    written = {}

    for name in chosen:
        renderer = RENDERERS.get(name)
        if not renderer:
            continue
        filename = "index.html" if name == "index" else f"report_{name}.html"
        path = output_dir / filename
        path.write_text(renderer(ctx), encoding="utf-8")
        written[name] = str(path)

    snapshot_path.write_text(
        json.dumps({**current, "saved_at": datetime.now().isoformat()}, indent=2),
        encoding="utf-8",
    )

    return written
