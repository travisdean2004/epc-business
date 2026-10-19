#!/usr/bin/env python
# # -*- coding: utf-8 -*-

import sys
import json
import argparse
import webbrowser
import subprocess
from time import sleep
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules import cfg

def cli_args():
    make_args = argparse.ArgumentParser(description="Collected Job Applications & Filters:")
    make_args.add_argument("--brwsr", choices=["firefox", "os"], default="firefox")
    make_args.add_argument("--read-only", action="store_true", help="no browser, just terminal stdout")
    make_args.add_argument("--payrate", action="store_true", help="do not show jobs without salary in J.D")
    make_args.add_argument("--type", choices=["Full-time", "Part-time", "Contract", "Remote"], help="filter for job terms (e.g Part / Full Time, Contract or Remote)")
    return make_args.parse_args()

args = cli_args()

def get_artifacts():
    return [str(fref) for fref in (Path(__file__).parent.parent / "artifacts/json").glob("*.json")]

def _get_location(job): return job.get("job_location") or job.get("location", "N/A")
def _get_query(job): return job.get("search_query") or job.get("query" , "N/A")
def _normalize_job_type(objct):
    if not objct or not isinstance(objct, str):
        return ""
    return objct.replace(" ", "").replace("-", "").lower()

    
def data_check():
    job_filter = []
    skip = {"Not Available", "N/A", "Pay information not provided", None, ""}
    for artifact_json in get_artifacts():
        with open(artifact_json, 'r') as read_init:
            infile = json.load(read_init)
            if isinstance(infile, dict) and "jobs" in infile:
                for job in infile["jobs"]:
                    if args.payrate:
                        salary = job.get("salary")
                        if not salary  or salary in skip:
                            continue
                    if args.type:
                        if _normalize_job_type(job.get("job_type")) != _normalize_job_type(args.type):
                            continue
                    job_term = job.get("job_type")
                    salary_value = job.get("salary", "N/A")
                    job_filter.append({
                        "details": job.get("job_details", {}).get("full_description", ""),
                        "skills": job.get("job_details", {}).get("skills", []),
                        "position_term": job_term,
                        "for": _get_query(job=job),
                        "company": job.get("company"),
                        "view": job.get("screenshot"),
                        "salary": salary_value,
                        "url": job.get("url"),
                        "where": _get_location(job=job),
                        "title": job.get("title")
                    })
    return job_filter

def main(delay:int):
    url_tracker = 0
    firefox = "/Applications/Firefox.app/Contents/MacOS/firefox"
    jobs = data_check()
    for idx, job in enumerate(jobs, start=1):
        cfg.cprint(f"\nJob ID: # {cfg.clrd(idx, 'yellow')}:"
                f"\n\tTitle:\t  {cfg.clrd(str(job['title']).upper(), 'bold')}"
                f"\n\tOrg Name: {cfg.clrd(str(job['company']).upper(), 'bold blue')}"
                f"\n\tPay Rate: {cfg.clrd(job['salary'], 'green')}"
                f"\n\t{cfg.clrd('Url', 'yellow')}: {cfg.clrd(job['url'], 'cyan')}")
    
    filters =[call for call in ["payrate" if args.payrate else None,  f"type={args.type}" if args.type else None] if call]
    cfg.cprint(f"\nThere are {cfg.clrd(len(jobs), 'yellow')} records based on {f'{cfg.clrd(', '.join(filters), 'red')} filters:' if filters else ''}:\n" + cfg.clrd('=', 'bold') * 65)

    if not args.read_only:
        for url_idx, job in enumerate(jobs, start=1):
            if args.brwsr == "firefox":
                subprocess.run([firefox, "-new-tab", f"{job['url']}"])
            else:
                webbrowser.open(url=job['url'])
            
            url_tracker += 1
            cfg.cprint(f"\t{cfg.clrd('Opened', 'magenta')}: {cfg.clrd(url_tracker, 'yellow')}/{cfg.clrd(len(jobs), 'green')}\t{cfg.clrd(job.get('company'), 'bold')}:")
            if url_tracker % 3 == 0 and url_idx < len(jobs):
                cfg.cprint(f"\n\t{cfg.clrd(url_tracker, 'cyan')} {cfg.clrd('in browser', 'green')} | {cfg.clrd(delay, 'bold')} seconds delay: \n\t" + cfg.clrd('-', 'bold')* 35)
                sleep(delay)
    
    cfg.cprint(f"\nDone! --> Went through {cfg.clrd(url_tracker, 'green')} urls out of {cfg.clrd(len(jobs), 'yellow')}")


if __name__ == "__main__":
    main(delay=30)
# ___________________________________________________________________________________________________________

