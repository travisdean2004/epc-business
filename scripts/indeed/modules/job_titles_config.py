#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Load and parse job title presets from config/job_titles.ini."""

import re
from configparser import ConfigParser
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "job_titles.ini"
FALLBACK_TITLES = ["Software Engineer", "SDET", "DevOps Engineer", "Staff Software Engineer", "Site Reliability Engineer",]


def job_titles_config_path():
    """Return path to job titles config file."""
    return DEFAULT_CONFIG


def load_job_titles(config_path=None):
    """Load ordered job titles from INI config.

    Returns:
        list[str]: Job titles in display order.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not path.exists():
        return list(FALLBACK_TITLES)

    parser = ConfigParser()
    parser.read(path, encoding="utf-8")
    if not parser.has_section("job_titles"):
        return list(FALLBACK_TITLES)

    items = []
    for key, value in parser.items("job_titles"):
        title = value.strip()
        if not title or title.startswith("#"):
            continue
        sort_key = _sort_key(key)
        items.append((sort_key, title))

    if not items:
        return list(FALLBACK_TITLES)

    items.sort(key=lambda pair: pair[0])
    return [title for _, title in items]


def _sort_key(key):
    """Sort numeric keys naturally; non-numeric keys go last."""
    match = re.match(r"^(\d+)", key.strip())
    if match:
        return (0, int(match.group(1)))
    return (1, key.lower())


def parse_title_selection(raw, titles):
    """Parse user selection into one or more job titles.

    Supports:
        - single index: 5
        - multiple indices: 1,5,8
        - range: 1-5 or 1,3-5,8
        - all presets: all, *, a
        - custom title text: Staff SDET Engineer
        - custom keyword: c or custom

    Returns:
        list[str]: Selected job titles (deduplicated, order preserved).
    """
    raw = (raw or "").strip()
    if not raw:
        return [titles[0]] if titles else ["Software Engineer"]

    if raw.lower() in ("c", "custom"):
        custom = input("Enter job title: ").strip()
        return [custom or "Software Engineer"]

    if raw.lower() in ("all", "*", "a"):
        return list(titles) if titles else ["Software Engineer"]

    if _looks_like_index_selection(raw):
        selected = _indices_to_titles(raw, titles)
        if selected:
            return selected
        print(f"[!] Invalid selection — use 1-{len(titles)}, ranges like 1-5, or all")
        return [titles[0]] if titles else ["Software Engineer"]

    return [raw]


def _indices_to_titles(raw, titles):
    """Expand index/range input into deduplicated title list."""
    selected = []
    seen = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        for idx in _expand_index_part(part, len(titles)):
            title = titles[idx - 1]
            if title not in seen:
                seen.add(title)
                selected.append(title)
    return selected


def _expand_index_part(part, max_idx):
    """Return 1-based indices from '5' or '1-5'."""
    if part.isdigit():
        idx = int(part)
        return [idx] if 1 <= idx <= max_idx else []

    if "-" in part:
        left, right = part.split("-", 1)
        left, right = left.strip(), right.strip()
        if left.isdigit() and right.isdigit():
            start, end = int(left), int(right)
            if start > end:
                start, end = end, start
            return [i for i in range(start, end + 1) if 1 <= i <= max_idx]
    return []


def _looks_like_index_selection(raw):
    """True when input is index/range only (e.g. 5, 1,5,8, or 1-5)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return False
    for part in parts:
        if part.isdigit():
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            if left.strip().isdigit() and right.strip().isdigit():
                continue
        return False
    return True
