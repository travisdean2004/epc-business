#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Argument Parser Module - CLI argument parsing for Indeed scraper"""

import argparse

def parse_args():
    """Parse command line arguments for auto and interactive modes:
        Returns: <-- argparse.Namespace: Parsed arguments: """
    
    # __ customized formatter improves help msgs:
    class CustomHelpFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
        def __init__(self, prog):
            super().__init__(prog, max_help_position=40, width=100)

    parser = argparse.ArgumentParser(description='Indeed Job Scraper - Cookie-Based Authentication with SeleniumBase UC Mode', 
                                     formatter_class=CustomHelpFormatter,
                                     epilog='''
    ======================================================================================================
                                *** CLI Examples Reference ***
    ======================================================================================================

    Interactive Mode - guided prompts:
        python main.py

    Basic Automated Search:
        python main.py --auto --query "DevOps Engineer"
        python main.py --auto --query "SDET" --location "Remote" --remote

    With Filters:
        python main.py --auto --query "Software Engineer" --location "Remote" --remote --min-salary 150000 --max-salary 200000 --days 7 --max 50

    Multiple Queries:
        python main.py --auto --queries "DevOps,SDET,SRE" --remote --days 7 --max 25

    With Screenshots:
        python main.py --auto --query "Backend Engineer" --remote --screenshots --max 25

    Headless Mode (servers/cron):
        python main.py --auto --query "Platform Engineer" --remote --headless --max 50

    With Proxy:
        python main.py --auto --query "Cloud Engineer" --proxy "http://user:pass@proxy.example.com:8080" --remote

    Custom Output Directory:
        python main.py --auto --query "DevOps" --output-dir "./results" --max 50

    Full Example:
        python main.py --auto --query "DevOps Engineer" --location "Remote" --remote --days 7 --max 50 --screenshots --output-dir "./artifacts/json"

    ======================================================================================================
        '''
    )
    
    # ================= OPERATION MODE ==========================
    mode_group = parser.add_argument_group('Operation Mode')
    mode_group.add_argument('--auto', action='store_true', help='Run in automated mode (no interactive prompts)')
    
    # ================= SEARCH PARAMETERS =======================
    search_group = parser.add_argument_group('Search Parameters')
    search_group.add_argument('--board', type=str, default='indeed', choices=['indeed', 'glassdoor', 'dice'], help='Job board to scrape (indeed, glassdoor, or dice)')
    search_group.add_argument('--query', type=str, help='Job search query (e.g., "DevOps Engineer")')
    search_group.add_argument('--queries', type=str, help='Multiple queries comma-separated (e.g., "DevOps,SDET,SRE")')
    search_group.add_argument('--location', type=str, default='Remote', help='Job location')
    search_group.add_argument('--remote', action='store_true', help='Filter for remote jobs only')
    
    # ================= FILTERS ================================
    filter_group = parser.add_argument_group('Filters')
    filter_group.add_argument('--min-salary', type=int, dest='min_salary', help='Minimum salary (e.g., 150000)')
    filter_group.add_argument('--max-salary', type=int, dest='max_salary', help='Maximum salary (e.g., 200000)')
    filter_group.add_argument('--days', type=int, choices=[1, 3, 7, 14], help='Posted within last N days')
    filter_group.add_argument('--max', type=int, default=25, help='Maximum results per search')
    
    # ================= BROWSER SETTINGS =======================
    browser_group = parser.add_argument_group('Browser Settings')
    browser_group.add_argument('--headless', action='store_true', help='Run browser in headless mode (no GUI)')
    browser_group.add_argument('--incognito', action='store_true', help='Run in incognito mode (fresh session, no saved cookies)')
    browser_group.add_argument('--window-size', type=str, default='maximized', dest='window_size', help='Window size: "maximized" or "WIDTHxHEIGHT" (e.g., "1280x720")')
    
    # ================= PROXY SETTINGS =========================
    proxy_group = parser.add_argument_group('Proxy Settings')
    proxy_group.add_argument('--proxy', type=str,help='Proxy server URL (e.g., "http://user:pass@proxy.example.com:8080")')
    proxy_group.add_argument('--proxy-user', type=str, dest='proxy_user', help='Proxy username (if not included in proxy URL)')
    proxy_group.add_argument('--proxy-pass', type=str, dest='proxy_pass', help='Proxy password (if not included in proxy URL)')
    
    # ================= OUTPUT SETTINGS ========================
    output_group = parser.add_argument_group('Output Settings')
    output_group.add_argument('--output-dir', type=str, default='artifacts/json',dest='output_dir', help='Output directory for JSON files')
    output_group.add_argument('--screenshots', action='store_true', help='Capture screenshots of pages and job cards')
    output_group.add_argument('--screenshots-dir', type=str, default='artifacts/screenshots', dest='screenshots_dir', help='Directory for screenshots')
    
    return parser.parse_args()


if __name__ == "__main__":
    # __ test argument parsing:
    args = parse_args()
    print(f"Parsed args: {args}")
