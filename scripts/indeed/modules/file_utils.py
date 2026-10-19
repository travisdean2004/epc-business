#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" File Utilities Module - File operations for saving artifacts """

import json
from pathlib import Path
from datetime import datetime


def format_timestamp(dt=None):
    """ Format timestamp in human-readable format:
        Args: dt (datetime): <-- Datetime object (default: now)
        Returns: str:        <-- Human-readable timestamp: """
    
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%B %d, %Y at %I:%M %p")


def format_filename_timestamp(dt=None):
    """ Format timestamp for filenames:
        Args: dt (datetime): <-- Datetime object (default: now)
        Returns: str:        <-- Filename-safe timestamp:"""
    
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y%m%d_%H%M%S")


def save_jobs_json(jobs, filename, output_dir="artifacts/json", jb_board=None):
    """ Save jobs to .json file plus metadata:
        Args:
            jobs (list):        <-- List of job dictionaries
            filename (str):     <-- Base filename (without extension or timestamp)
            output_dir (str):   <-- Output directory path
        Returns:                <-- Path: Path to saved file, or None if no jobs: """
    if not jobs:
        print("No jobs to save")
        return None
    
    # ___  output directory exists check:
    output_path = Path(__file__).parent.parent / output_dir
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = format_filename_timestamp()
    now = datetime.now()
    search_query = (jobs[0].get("search_query") or jobs[0].get("query", "N/A")) if jobs else "N/A"
    search_location = (
        jobs[0].get("search_location") or jobs[0].get("location") or jobs[0].get("job_location", "N/A")
    ) if jobs else "N/A"

    if jb_board == "dice":
        filepath = output_path / f"dice_data_{filename}_{timestamp}.json"
        output = {
            "metadata": {
                "board": "dice",
                "source": "Dice.com",
                "total_jobs": len(jobs),
                "scraped_at": now.isoformat(),
                "scraped_at_readable": format_timestamp(now),
                "search_params": {
                    "query": search_query,
                    "location": search_location,
                },
                "pages_scraped": max([job.get("page", 1) for job in jobs]) if jobs else 1,
                "detailed_scraping_enabled": any(job.get("detailed_scraped", False) for job in jobs),
            },
            "jobs": jobs,
        }
    elif jb_board == "glassdoor":
        filepath = output_path / f"glassdoor_data_{filename}_{timestamp}.json"
        output = {
            "metadata": {
                "board": "glassdoor",
                "source": "Glassdoor.com",
                "total_jobs": len(jobs),
                "scraped_at": now.isoformat(),
                "scraped_at_readable": format_timestamp(now),
                "search_params": {
                    "query": search_query,
                    "location": search_location,
                },
            },
            "jobs": jobs,
        }
    else:
        filepath = output_path / f"{filename}_{timestamp}.json"
        output = {
            "metadata": {
                "board": jb_board or "indeed",
                "source": "Indeed.com",
                "total_jobs": len(jobs),
                "scraped_at": now.isoformat(),
                "scraped_at_readable": format_timestamp(now),
                "search_params": {
                    "query": search_query,
                    "location": search_location,
                },
            },
            "jobs": jobs,
        }
    
    # ___ write to file:
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Saved {len(jobs)} jobs to: {filepath}")
    return filepath

# def save_jobs_json(jobs, filename, output_dir="artifacts/json"):
#     """ Save jobs to .json file plus metadata:
#         Args:
#             jobs (list):        <-- List of job dictionaries
#             filename (str):     <-- Base filename (without extension or timestamp)
#             output_dir (str):   <-- Output directory path
#         Returns:                <-- Path: Path to saved file, or None if no jobs: """
#     if not jobs:
#         print("No jobs to save")
#         return None
    
#     # ___  output directory exists check:
#     output_path = Path(__file__).parent.parent / output_dir
#     output_path.mkdir(parents=True, exist_ok=True)
    
#     # ___ touch filename with timestamp:
#     timestamp = format_filename_timestamp()
#     filepath = output_path / f"{filename}_{timestamp}.json"
    
#     # ___ metadata output map:
#     now = datetime.now()
#     output = {
#         'metadata': {
#             'total_jobs': len(jobs),
#             'scraped_at': now.isoformat(),
#             'scraped_at_readable': format_timestamp(now),
#             'search_params': {
#                 'query': jobs[0].get('search_query', 'N/A') if jobs else 'N/A',
#                 'location': jobs[0].get('search_location', 'N/A') if jobs else 'N/A',
#             }
#         },
#         'jobs': jobs
#     }
    
#     # ___ write to file:
#     with open(filepath, 'w', encoding='utf-8') as f:
#         json.dump(output, f, indent=2, ensure_ascii=False)
    
#     print(f"\n✓ Saved {len(jobs)} jobs to: {filepath}")
#     return filepath


def save_log(message, log_type="info"):
    """ Save log message to log file:
        Args:
            message (str):  <-- Log message:
            log_type (str): <-- Log type (info, error, debug)"""
    log_dir = Path(__file__).parent.parent / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d")
    log_file = log_dir / f"scraper_{timestamp}.log"
    
    log_entry = f"[{format_timestamp()}] [{log_type.upper()}] {message}\n"
    
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)


def get_artifact_paths():
    """ Get paths to artifact directories:
        Returns: dict:  <-- Dictionary of artifact directory paths: """
    base_path = Path(__file__).parent.parent / "artifacts"
    return {
        'json': base_path / "json",
        'html': base_path / "html",
        'logs': base_path / "logs"
    }


if __name__ == "__main__":
    pass
    # print(format_timestamp())
    # print(format_filename_timestamp())
    # print(get_artifact_paths())
