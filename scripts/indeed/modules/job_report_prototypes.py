#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Generate 3 themed UI prototypes for job reports (slate / focus / console)."""

import html
import re
from pathlib import Path
from urllib.parse import quote_plus

from modules.job_report_html import (
    HTML_DIR,
    METRIC_TIPS,
    _clean_field,
    _current_stats,
    _esc,
    _interactive_js,
    _job_actions_html,
    _job_sort_attrs,
    build_report_context,
)

PROTO_DIR = HTML_DIR / "prototypes"

THEMES = {
    "slate": {
        "label": "Clean Slate",
        "tagline": "Light, airy, table-first — minimal noise",
        "css": """
:root {
  --bg:#eef2f7; --panel:#fff; --panel2:#f8fafc; --text:#0f172a; --muted:#64748b;
  --line:#dbe3ee; --accent:#2563eb; --accent-soft:#dbeafe; --company:#b45309;
  --tag-bg:#f1f5f9; --head:#f8fafc; --shadow:0 1px 3px rgba(15,23,42,.08);
  --radius:10px; --row-h:42px;
}
body { font-family: 'Segoe UI', system-ui, sans-serif; }
""",
    },
    "focus": {
        "label": "Focus Dark",
        "tagline": "Compact dark UI — sticky headers, one-line tags",
        "css": """
:root {
  --bg:#0f1419; --panel:#161d27; --panel2:#1c2533; --text:#e8eef6; --muted:#8b9cb3;
  --line:#273244; --accent:#38bdf8; --accent-soft:#0c4a6e; --company:#fbbf24;
  --tag-bg:#1f2937; --head:#121820; --shadow:0 2px 8px rgba(0,0,0,.35);
  --radius:8px; --row-h:38px;
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
""",
    },
    "console": {
        "label": "Ops Console",
        "tagline": "Dense ops view — filters left, data center, quick scan",
        "css": """
:root {
  --bg:#0a0e14; --panel:#111820; --panel2:#151c26; --text:#c9d1d9; --muted:#7d8590;
  --line:#21262d; --accent:#ffb454; --accent-soft:#3d2a0a; --company:#ffd580;
  --tag-bg:#1a2332; --head:#0d1117; --shadow:inset 0 1px 0 rgba(255,255,255,.04);
  --radius:6px; --row-h:36px;
}
body { font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace; font-size:13px; }
.stat-num { font-family: inherit; }
""",
    },
}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "unknown").lower()).strip("-") or "unknown"


def _company_link(name, theme):
    slug = _slug(name)
    return f'<a class="co-link" href="{theme}/companies.html#{slug}">{_esc(name or "Unknown")}</a>'


def _google_link(name):
    q = quote_plus(f"{name} company careers")
    return f"https://www.google.com/search?q={q}"


def _indeed_company_link(name):
    return f"https://www.indeed.com/jobs?q={quote_plus(name or '')}"


def build_company_profiles(jobs):
    profiles = {}
    for job in jobs:
        name = job.get("company_display") or job.get("company") or "Unknown"
        slug = _slug(name)
        if slug not in profiles:
            profiles[slug] = {
                "name": name,
                "slug": slug,
                "jobs": [],
                "urls": [],
                "locations": set(),
                "positions": set(),
            }
        p = profiles[slug]
        p["jobs"].append(job)
        loc = _clean_field(job.get("location"))
        if loc:
            p["locations"].add(loc)
        pos = _clean_field(job.get("search_query"))
        if pos:
            p["positions"].add(pos)
        url = _clean_field(job.get("url"))
        if url and url not in p["urls"]:
            p["urls"].append(url)
    for p in profiles.values():
        p["locations"] = sorted(p["locations"])
        p["positions"] = sorted(p["positions"])
        p["job_count"] = len(p["jobs"])
    return sorted(profiles.values(), key=lambda x: (-x["job_count"], x["name"].lower()))


def _shared_proto_css():
    return """
* { box-sizing: border-box; }
body { margin: 0; line-height: 1.45; background: var(--bg); color: var(--text); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: min(1680px, 98vw); margin: 0 auto; padding: 20px 24px 48px; }
.topbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 20px; margin-bottom: 20px; padding: 14px 16px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); }
.topbar h1 { margin: 0; font-size: 20px; font-weight: 700; }
.topbar .tagline { color: var(--muted); font-size: 13px; margin: 0; }
.nav { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }
.nav a { padding: 6px 12px; border-radius: 999px; border: 1px solid var(--line); color: var(--text); font-size: 12px; font-weight: 600; text-decoration: none; }
.nav a:hover { border-color: var(--accent); color: var(--accent); }
.nav a.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.sub { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.panel-head { padding: 12px 16px; border-bottom: 1px solid var(--line); display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.panel-head h2 { margin: 0; font-size: 15px; font-weight: 700; }
.panel-body { padding: 0; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 18px; }
.stat-tile { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; cursor: pointer; text-align: left; color: inherit; width: 100%; box-shadow: var(--shadow); transition: border-color .12s; }
.stat-tile:hover, .stat-tile.open { border-color: var(--accent); }
.stat-num { display: block; font-size: 28px; font-weight: 800; line-height: 1.1; }
.stat-label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stat-info { display: none; margin: 0 0 16px; padding: 12px 14px; background: var(--accent-soft); border: 1px solid var(--accent); border-radius: var(--radius); font-size: 13px; color: var(--text); }
.stat-info.open { display: block; }
.filter-bar { display: flex; flex-wrap: wrap; gap: 6px; }
.filter-btn { background: var(--panel2); color: var(--text); border: 1px solid var(--line); border-radius: 999px; padding: 5px 12px; font-size: 12px; cursor: pointer; white-space: nowrap; }
.filter-btn:hover, .filter-btn.active { border-color: var(--accent); color: var(--accent); }
.table-wrap { overflow: auto; max-height: min(72vh, 900px); }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; min-width: 1100px; }
.data-table th { position: sticky; top: 0; z-index: 2; background: var(--head); text-align: left; padding: 8px 10px; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); border-bottom: 1px solid var(--line); white-space: nowrap; cursor: pointer; user-select: none; }
.data-table th.sort-asc::after { content: ' ▲'; color: var(--accent); }
.data-table th.sort-desc::after { content: ' ▼'; color: var(--accent); }
.data-table td { padding: 0 10px; height: var(--row-h); vertical-align: middle; border-bottom: 1px solid var(--line); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.data-table tr:hover td { background: var(--panel2); }
.data-table tr.is-hidden { display: none; }
.data-table .col-status { width: 130px; }
.data-table .col-co { width: 14%; }
.data-table .col-pos { width: 12%; }
.data-table .col-title { width: 22%; }
.data-table .col-loc { width: 14%; }
.data-table .col-salary { width: 12%; }
.data-table .col-seen { width: 56px; text-align: right; }
.data-table .col-act { width: 280px; }
.co-link { color: var(--company); font-weight: 700; }
.tag-row { display: inline-flex; flex-wrap: nowrap; gap: 4px; max-width: 100%; overflow: hidden; vertical-align: middle; }
.tag { display: inline-block; padding: 2px 7px; border-radius: 3px; font-size: 10px; font-weight: 700; line-height: 1.3; white-space: nowrap; background: var(--tag-bg); border: 1px solid var(--line); }
.tag-new { color: #059669; border-color: #6ee7b7; }
.tag-known { color: #2563eb; border-color: #93c5fd; }
.tag-user { color: #047857; background: #ecfdf5; border-color: #6ee7b7; }
.tag-warn { color: #b45309; border-color: #fcd34d; }
.tag-ghost { color: #b91c1c; border-color: #fca5a5; }
.meta { color: var(--muted); font-size: 12px; }
.company-block { padding: 16px; border-bottom: 1px solid var(--line); scroll-margin-top: 80px; }
.company-block:last-child { border-bottom: none; }
.company-block h3 { margin: 0 0 8px; font-size: 17px; }
.company-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }
.company-links a { font-size: 12px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel2); }
.job-link-list { margin: 8px 0 0; padding-left: 18px; font-size: 12px; max-height: 160px; overflow: auto; }
.layout-split { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 960px) { .layout-split { grid-template-columns: 1fr; } }
.side-panel { padding: 12px; }
.side-panel h3 { margin: 0 0 10px; font-size: 12px; text-transform: uppercase; color: var(--muted); letter-spacing: .05em; }
.btn { background: var(--panel2); color: var(--text); border: 1px solid var(--line); border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; white-space: nowrap; display: inline-block; }
.btn:hover { border-color: var(--accent); }
.btn-open { color: var(--accent); }
.btn-apply.is-done { color: #059669; border-color: #6ee7b7; cursor: default; }
.job-actions { display: inline-flex; flex-wrap: nowrap; gap: 4px; align-items: center; }
.empty { padding: 24px; text-align: center; color: var(--muted); font-style: italic; }
"""


def _compact_tags(job):
    parts = []
    app_st = job.get("application_status") or "none"
    if app_st == "applied":
        parts.append('<span class="tag tag-user">applied</span>')
    elif app_st in ("skipped", "interviewing", "offer", "rejected"):
        parts.append(f'<span class="tag tag-warn">{_esc(app_st)}</span>')
    flags = job.get("flags") or []
    if "ghost_candidate" in flags:
        parts.append('<span class="tag tag-ghost">ghost</span>')
    elif "repost" in flags:
        parts.append('<span class="tag tag-warn">repost</span>')
    seen = job.get("seen_count", 1) or 1
    if seen == 1 and app_st == "none":
        parts.append('<span class="tag tag-new">new</span>')
    elif seen > 1 and app_st == "none" and "ghost_candidate" not in flags:
        parts.append('<span class="tag tag-known">seen</span>')
    if not parts:
        parts.append('<span class="tag">—</span>')
    return f'<span class="tag-row">{"".join(parts[:3])}</span>'


def _job_row_proto(job, theme):
    company = job.get("company_display") or job.get("company") or "Unknown"
    title = job.get("title") or ""
    position = _clean_field(job.get("search_query")) or "—"
    location = job.get("location") or "—"
    salary = job.get("salary") or "—"
    seen = job.get("seen_count", 1)
    attrs = _job_sort_attrs(job)
    app_st = job.get("application_status") or "none"
    actions = _job_actions_html(job, compact=True)
    return f"""<tr {attrs} data-application-status="{_esc(app_st)}">
  <td class="col-status">{_compact_tags(job)}</td>
  <td class="col-co">{_company_link(company, theme)}</td>
  <td class="col-pos" title="{_esc(position)}">{_esc(position)}</td>
  <td class="col-title" title="{_esc(title)}">{_esc(title)}</td>
  <td class="col-loc" title="{_esc(location)}">{_esc(location)}</td>
  <td class="col-salary" title="{_esc(salary)}">{_esc(salary)}</td>
  <td class="col-seen">{seen}</td>
  <td class="col-act">{actions}</td>
</tr>"""


def _proto_shell(theme_key, page, title, body, active_page):
    theme = THEMES[theme_key]
    nav_items = [
        ("overview", "Overview", f"{theme_key}/overview.html"),
        ("jobs", "Jobs", f"{theme_key}/jobs.html"),
        ("companies", "Companies", f"{theme_key}/companies.html"),
    ]
    nav_html = "".join(
        f'<a href="../{href}" class="{"active" if pid == active_page else ""}">{label}</a>'
        for pid, label, href in nav_items
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · {theme['label']}</title>
<style>
{theme['css']}
{_shared_proto_css()}
</style>
</head>
<body>
<div class="wrap">
  <header class="topbar">
    <div>
      <h1>{theme['label']}</h1>
      <p class="tagline">{theme['tagline']}</p>
    </div>
    <nav class="nav">{nav_html}<a href="../index.html">All themes</a></nav>
  </header>
  {body}
</div>
{_proto_js()}
</body>
</html>"""


def _proto_js():
    extra = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.stat-tile').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.infoTarget;
      const panel = id ? document.getElementById(id) : null;
      const open = panel && !panel.classList.contains('open');
      document.querySelectorAll('.stat-info').forEach((p) => p.classList.remove('open'));
      document.querySelectorAll('.stat-tile').forEach((b) => b.classList.remove('open'));
      if (open && panel) {
        panel.classList.add('open');
        btn.classList.add('open');
      }
    });
  });
});
</script>"""
    return _interactive_js() + extra


def _stat_tiles(ctx, keys):
    db = ctx.get("db_summary") or {}
    current = _current_stats(ctx)
    tiles = []
    for key in keys:
        val = current.get(key, "—")
        tip = METRIC_TIPS.get(key, "")
        label = key.replace("_", " ")
        tiles.append(f"""
<button type="button" class="stat-tile" data-info-target="info-{_esc(key)}">
  <span class="stat-num">{val}</span>
  <span class="stat-label">{_esc(label)}</span>
</button>
<div class="stat-info" id="info-{_esc(key)}">{_esc(tip)}</div>""")
    return f'<div class="stat-grid">{"".join(tiles)}</div>'


def render_proto_overview(theme_key, ctx):
    db = ctx["db_summary"]
    profiles = build_company_profiles(ctx["db_jobs"][:200])
    top_cos = profiles[:8]
    co_rows = ""
    for p in top_cos:
        co_rows += f"""<tr>
          <td>{_company_link(p['name'], theme_key)}</td>
          <td style="text-align:right">{p['job_count']}</td>
          <td class="meta">{_esc(', '.join(p['positions'][:2]) or '—')}</td>
        </tr>"""

    body = f"""
    <h2 style="margin:0 0 6px;font-size:22px">Overview</h2>
    <p class="sub">Generated {_esc(ctx['generated_at'])} · click a stat tile for details · DB {'ready' if db.get('exists') else 'empty'}</p>
    {_stat_tiles(ctx, ['jobs', 'companies', 'sightings', 'ghost_candidates'])}
    <div class="panel">
      <div class="panel-head"><h2>Top employers in DB</h2><a href="jobs.html">Open all jobs →</a></div>
      <div class="panel-body table-wrap">
        <table class="data-table" style="min-width:600px">
          <thead><tr><th>Company</th><th style="width:80px;text-align:right">Jobs</th><th>Positions seen</th></tr></thead>
          <tbody>{co_rows or '<tr><td colspan="3" class="empty">No data</td></tr>'}</tbody>
        </table>
      </div>
    </div>"""
    return _proto_shell(theme_key, "overview", "Overview", body, "overview")


def render_proto_jobs(theme_key, ctx):
    rows = "".join(_job_row_proto(j, theme_key) for j in ctx["db_jobs"][:250])
    thead = """<tr>
      <th class="sortable col-status" data-sort="company" data-sort-type="text">Status</th>
      <th class="sortable col-co" data-sort="company">Company</th>
      <th class="sortable col-pos" data-sort="position">Position</th>
      <th class="sortable col-title" data-sort="title">Title</th>
      <th class="sortable col-loc" data-sort="location">Location</th>
      <th class="sortable col-salary" data-sort="salary" data-sort-type="num">Salary</th>
      <th class="sortable col-seen" data-sort="seen" data-sort-type="num">Seen</th>
      <th class="col-act">Actions</th>
    </tr>"""
    table = f"""
        <table id="jobs-table" class="data-table sortable-table">
          <thead>{thead}</thead>
          <tbody>{rows or '<tr><td colspan="8" class="empty">No jobs</td></tr>'}</tbody>
        </table>"""
    filters = """
    <div class="filter-bar" data-filter-target="#jobs-table tbody tr" style="margin-bottom:12px">
      <button type="button" class="filter-btn active" data-filter="all">All</button>
      <button type="button" class="filter-btn" data-filter="open">To review</button>
      <button type="button" class="filter-btn" data-filter="applied">Applied by you</button>
      <button type="button" class="filter-btn" data-filter="skipped">Skipped</button>
      <button type="button" class="filter-btn" data-filter="interview">Interviewing</button>
    </div>"""

    if theme_key == "console":
        body = f"""
    <h2 style="margin:0 0 6px;font-size:22px">Jobs</h2>
    <p class="sub">Dense ops layout · sticky header · single-line tags</p>
    <div class="layout-split">
      <div class="panel side-panel">
        <h3>Filter</h3>
        <div class="filter-bar" data-filter-target="#jobs-table tbody tr" style="flex-direction:column;align-items:stretch">
          <button type="button" class="filter-btn active" data-filter="all">All</button>
          <button type="button" class="filter-btn" data-filter="open">To review</button>
          <button type="button" class="filter-btn" data-filter="applied">Applied</button>
          <button type="button" class="filter-btn" data-filter="skipped">Skipped</button>
          <button type="button" class="filter-btn" data-filter="interview">Interview</button>
        </div>
      </div>
      <div class="panel"><div class="panel-body table-wrap">{table}</div></div>
    </div>"""
    else:
        body = f"""
    <h2 style="margin:0 0 6px;font-size:22px">Jobs</h2>
    <p class="sub">{len(ctx['db_jobs'])} jobs · click stat-style headers to sort · one row per listing</p>
    {filters}
    <div class="panel"><div class="panel-body table-wrap">{table}</div></div>"""
    return _proto_shell(theme_key, "jobs", "Jobs", body, "jobs")


def render_proto_companies(theme_key, ctx):
    profiles = build_company_profiles(ctx["db_jobs"])
    index_rows = ""
    blocks = ""
    for p in profiles[:60]:
        index_rows += f"""<tr>
          <td>{_company_link(p['name'], theme_key)}</td>
          <td style="text-align:right">{p['job_count']}</td>
          <td class="meta">{_esc(', '.join(p['locations'][:2]) or '—')}</td>
        </tr>"""
        links = f"""
          <a href="{_google_link(p['name'])}" target="_blank" rel="noopener">Google</a>
          <a href="{_indeed_company_link(p['name'])}" target="_blank" rel="noopener">Indeed search</a>"""
        job_links = ""
        for job in p["jobs"][:15]:
            url = _clean_field(job.get("url"))
            title = job.get("title") or "Job"
            if url:
                job_links += f'<li><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(title)}</a></li>'
            else:
                job_links += f"<li>{_esc(title)}</li>"
        if len(p["jobs"]) > 15:
            job_links += f'<li class="meta">+ {len(p["jobs"]) - 15} more listings</li>'

        blocks += f"""
<section class="company-block" id="{p['slug']}">
  <h3>{_esc(p['name'])} <span class="meta">({p['job_count']} listings)</span></h3>
  <div class="company-links">{links}</div>
  <p class="meta">Positions: {_esc(', '.join(p['positions']) or '—')} · Locations: {_esc(', '.join(p['locations'][:5]) or '—')}</p>
  <ul class="job-link-list">{job_links or '<li class="meta">No URLs stored</li>'}</ul>
</section>"""

    body = f"""
    <h2 style="margin:0 0 6px;font-size:22px">Companies</h2>
    <p class="sub">Directory with external links + Indeed posting URLs from your scrapes</p>
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-body table-wrap" style="max-height:240px">
        <table class="data-table" style="min-width:640px">
          <thead><tr><th>Company</th><th style="width:70px;text-align:right">Jobs</th><th>Locations</th></tr></thead>
          <tbody>{index_rows or '<tr><td colspan="3" class="empty">No companies</td></tr>'}</tbody>
        </table>
      </div>
    </div>
    <div class="panel"><div class="panel-body">{blocks or '<div class="empty">No companies</div>'}</div></div>"""
    return _proto_shell(theme_key, "companies", "Companies", body, "companies")


def render_proto_index():
    cards = ""
    for key, theme in THEMES.items():
        cards += f"""
        <a class="panel" href="{key}/overview.html" style="display:block;padding:18px;text-decoration:none;color:inherit">
          <h3 style="margin:0 0 6px;color:var(--accent)">{theme['label']}</h3>
          <p class="meta" style="margin:0 0 12px">{theme['tagline']}</p>
          <span class="btn">Open prototype →</span>
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Report UI Prototypes</title>
<style>
:root {{ --bg:#0f1419; --panel:#161d27; --text:#e8eef6; --muted:#8b9cb3; --line:#273244; --accent:#38bdf8; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }}
.wrap {{ max-width:960px; margin:0 auto; padding:32px 20px; }}
h1 {{ margin:0 0 8px; }} .sub {{ color:var(--muted); margin-bottom:24px; }}
.grid {{ display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }}
a.panel:hover {{ border-color:var(--accent); }}
.panel {{ border:1px solid var(--line); border-radius:10px; background:var(--panel); }}
.back {{ display:inline-block; margin-top:24px; color:var(--accent); }}
</style></head><body><div class="wrap">
<h1>Report UI Prototypes</h1>
<p class="sub">Three theme sets — pick one to compare. Each has Overview, Jobs, and Companies pages.</p>
<div class="grid">{cards}</div>
<a class="back" href="../index.html">← Back to current reports</a>
</div></body></html>"""


def generate_prototypes(json_dir=None, db_path=None, output_dir=None):
    output_dir = Path(output_dir) if output_dir else PROTO_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_report_context(json_dir=json_dir, db_path=db_path)

    written = {}
    (output_dir / "index.html").write_text(render_proto_index(), encoding="utf-8")
    written["prototypes/index"] = str(output_dir / "index.html")

    for theme_key in THEMES:
        theme_dir = output_dir / theme_key
        theme_dir.mkdir(parents=True, exist_ok=True)
        pages = {
            "overview.html": render_proto_overview(theme_key, ctx),
            "jobs.html": render_proto_jobs(theme_key, ctx),
            "companies.html": render_proto_companies(theme_key, ctx),
        }
        for fname, html_text in pages.items():
            path = theme_dir / fname
            path.write_text(html_text, encoding="utf-8")
            written[f"prototypes/{theme_key}/{fname}"] = str(path)

    return written
