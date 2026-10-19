#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" UI Module: Handles interactive user interface and job browsing """

import time
from modules.job_titles_config import (job_titles_config_path, load_job_titles, parse_title_selection,)

def job_board_portal():
    """ Prompt user for job board selection only:
        Returns: str: <-- Board name ('indeed', 'glassdoor', or 'dice'): """
    
    print("\nSelect job board:")
    print("\t\t1. -> Indeed")
    print("\t\t2. -> Glassdoor")
    print("\t\t3. -> Dice")
    choice = input("Enter choice (1-3, default 1): ").strip() or "1"
    
    if choice == "1":
        return "indeed"
    elif choice == "2":
        return "glassdoor"
    elif choice == "3":
        return "dice"
    else:
        print("[!] Invalid choice, defaulting to Indeed")
        return "indeed"
    

def prompt_job_titles(board=None):
    """Show preset job titles and let user pick by index or enter custom text.
        Args: board (str): Optional job board name for display context.
        Returns: list[str]: One or more job titles to search."""
    
    titles = load_job_titles()
    board_label = (board or "job board").replace("_", " ").title()

    print("\n" + "=" * 80)
    print(f"Job Titles — {board_label}")
    print("=" * 80)
    print(f"Config: {job_titles_config_path()}")
    print("\nPreset titles:")
    for idx, title in enumerate(titles, 1):
        print(f"  {idx:>2}. {title}")

    print("\nSelect job title(s):")
    print("  • Single index:     5")
    print("  • Multiple indices: 1,5,8")
    print("  • Range:            1-5   or   1,3-5,8")
    print("  • All presets:      all")
    print("  • Custom title:     type text (e.g. Staff SDET Engineer)")
    print("  • Custom prompt:    c  or  custom")

    choice = input("\nChoice (default 1): ").strip() or "1"
    selected = parse_title_selection(choice, titles)

    print(f"\nSelected ({len(selected)} title{'s' if len(selected) != 1 else ''}):")
    for title in selected:
        print(f"  → {title}")

    return selected


def display_jobs_interactive(jobs):
    """Interactive job browser with pagination:
        Args: <-- jobs (list): List of job dictionaries:"""
    
    if not jobs:
        return
    
    page_size = 5
    current_page = 0
    total_pages = (len(jobs) + page_size - 1) // page_size
    
    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(jobs))
        
        print(f"\n{'='*80}")
        print(f"Jobs {start_idx + 1}-{end_idx} of {len(jobs)} (Page {current_page + 1}/{total_pages})")
        print(f"{'='*80}\n")
        
        for i, job in enumerate(jobs[start_idx:end_idx], start=start_idx + 1):
            print(f"{i}. {job['title']}")
            print(f"   Company: {job['company']}")
            print(f"   Location: {job['location']}")
            if job['salary'] != "N/A":
                print(f"   Salary: {job['salary']}")
            print(f"   URL: {job['url']}")
            if job['snippet'] != "N/A":
                snippet = job['snippet'][:100]
                print(f"   Snippet: {snippet}...")
            print(f"   {'-'*76}")
        
        print("\nNavigation:")
        next_page_label = f" ({current_page + 2}/{total_pages})" if current_page < total_pages - 1 else " (end)"
        prev_page_label = f" ({current_page}/{total_pages})" if current_page > 0 else " (start)"
        
        print(f"  [n] Next page{next_page_label}")
        print(f"  [p] Previous page{prev_page_label}")
        print("  [#] View job details (enter job number)")
        print("  [q] Quit and close browser")
        
        choice = input("\nChoice: ").strip().lower()
        
        if choice == 'n' and current_page < total_pages - 1:
            current_page += 1
        elif choice == 'p' and current_page > 0:
            current_page -= 1
        elif choice == 'q':
            break
        elif choice.isdigit():
            job_num = int(choice) - 1
            if 0 <= job_num < len(jobs):
                display_job_details(jobs[job_num])
            else:
                print(f"Invalid number. Enter 1-{len(jobs)}")
                time.sleep(1)
        else:
            print("Invalid choice")
            time.sleep(1)


def display_job_details(job):
    """ Display detailed information for a single job:
        Args: <-- job (dict): Job dictionary: """
    
    print(f"\n{'='*80}")
    print(f"Job Details: {job['title']}")
    print(f"{'='*80}")
    print(f"Company: {job['company']}")
    print(f"Location: {job['location']}")
    print(f"Salary: {job['salary']}")
    print(f"Posted: {job['posted']}")
    print("\nDescription:")
    print(f"{job['snippet']}")
    print(f"\nApply: {job['url']}")
    print(f"{'='*80}")
    input("\nPress Enter to continue...")


def _prompt_optional_int(prompt, default=None):
    """Read an optional integer; empty input returns default."""
    raw = input(prompt).strip().replace(",", "").replace("$", "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  [!] Invalid number {raw!r} — using default")
        return default


def prompt_interactive_config(queries=None):
    """ Prompt user for search configuration in interactive mode:
        Args:
            queries (list): Pre-selected job titles (optional).
        Returns: dict: <-- Configuration dictionary:"""
    
    print("\n" + "="*80)
    print("Search Configuration")
    print("="*80)
    
    config = {}
    
    if queries:
        config['queries'] = list(queries)
        config['query'] = queries[0]
    else:
        config['query'] = input("\nJob title (e.g., 'SDET'): ") or "Software Engineer"
        config['queries'] = [config['query']]

    location_input = input("Location (empty for Remote): ")
    config['remote_only'] = input("Remote only? (y/n): ").lower() == 'y'
    
    # ___ if remote_only, ignore location input:
    if config['remote_only']:
        config['location'] = ""
    else:
        config['location'] = location_input or "Remote"
    
    use_salary = input("Salary filter? (y/n): ").lower() == 'y'
    if use_salary:
        min_salary = _prompt_optional_int("Min salary (empty to skip): ")
        max_salary = _prompt_optional_int("Max salary (empty to skip): ")
        if min_salary is not None and max_salary is not None:
            config['min_salary'] = min_salary
            config['max_salary'] = max_salary
        else:
            print("  Salary filter skipped (need both min and max)")
            config['min_salary'] = None
            config['max_salary'] = None
    else:
        config['min_salary'] = None
        config['max_salary'] = None
    
    print("\nDate: 1=24h, 3=3days, 7=7days, 14=14days")
    config['date_posted'] = _prompt_optional_int("Days (empty for all): ")
    config['max_results'] = _prompt_optional_int("Max results (default 25): ", default=25)
    
    return config

# def prompt_login():
#     """ Prompt user for login credentials:
#         Returns: tuple: <-- (email, password) or (None, None) if no login:"""
    
#     use_login = input("\nLogin? (y/n): ").lower() == 'y'
    
#     if use_login:
#         email = input("Indeed email: ")
#         password = input("Indeed password: ")
#         return email, password
    
#     return None, None
def print_header(title):
    """ Print formatted header:
        Args: title (str): Header title:"""
    print(f"\n\n\t*** {title.upper()} ***")


def print_summary(total_queries, total_jobs, start_time, end_time):
    """ Print scraping summary:
        Args:
            total_queries (int): Number of queries executed
            total_jobs (int): Total jobs scraped
            start_time (datetime): Start time
            end_time (datetime): End time: """
    from modules.file_utils import format_timestamp
    
    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"Total queries: {total_queries}")
    print(f"Total jobs scraped: {total_jobs}")
    print(f"Started: {format_timestamp(start_time)}")
    print(f"Completed: {format_timestamp(end_time)}")
    duration = (end_time - start_time).total_seconds()
    print(f"Duration: {int(duration // 60)}m {int(duration % 60)}s")
