#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Helper function to display cookie file age: """

import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules import cfg

cookie_artifact = "indeed_cookies.pkl"

def cookie_info(cookie_file=cookie_artifact):
    """ Display cookie file information including path and age.
            Args:          <-- cookie_file (str): Path to cookie file    
            Returns: dict: <-- Cookie file info or None if not found:"""
    
    root = Path(__file__).parents[1]
    cookie_path = root / cookie_file
    
    if not cookie_path.exists():
        return None
    
    # ___ get file stats:
    file_stats = os.stat(cookie_path)
    modified_timestamp = file_stats.st_mtime
    modified_datetime = datetime.fromtimestamp(modified_timestamp)
    
    # ___ calculate existing cookies age:
    now = datetime.now()
    age = now - modified_datetime
    
    # ___ human readable age format:
    if age.days > 0:
        if age.days == 1:
            age_str = "1 day old"
        elif age.days < 7:
            age_str = f"{age.days} days old"
        elif age.days < 30:
            weeks = age.days // 7
            age_str = f"{weeks} week{'s' if weeks > 1 else ''} old"
        else:
            months = age.days // 30
            age_str = f"{months} month{'s' if months > 1 else ''} old"
    elif age.seconds >= 3600:
        hours = age.seconds // 3600
        age_str = f"{hours} hour{'s' if hours > 1 else ''} old"
    elif age.seconds >= 60:
        minutes = age.seconds // 60
        age_str = f"{minutes} minute{'s' if minutes > 1 else ''} old"
    else:
        age_str = "just now"
    
    # ___ check if cookies are > 30 days | possibly expired:
    is_expired = age.days > 30
    
    return {
        'artifact_path': str(cookie_path.absolute()),
        'artifact_name': str(cookie_path.name),
        'modified': modified_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        'age': age_str,
        'age_days': age.days,
        'is_expired': is_expired
    }


def print_cookie_file_info(cookie_file=cookie_artifact):
    """ Print cookie file information in a formatted way:
        Args: <-- cookie_file (str): Path to cookie file: """
    
    info = cookie_info(cookie_file)
    if not info:
        cfg.cprint(f"\nExpected {cfg.clrd(cookie_file, 'yellow')} cookies artifact was {cfg.clrd('not found:', 'red')}\n", end="=" * 60 + "\n")
        return False
    
    cfg.cprint(f"\nFound:\t--> {cfg.clrd(info['artifact_name'], 'green')} file:")
    cfg.cprint(f"Path:\t--> {cfg.clrd(f"{info['artifact_path']}", 'magenta')}")
    cfg.cprint(f"Last updated: {cfg.clrd(f"{info['modified']}", 'yellow')} {cfg.clrd(f"{info['age']}", 'green')}\n")
    
    if info['is_expired']:
        cfg.cprint(f"{cfg.clrd('\n\tWARNING:', 'red')} "
                f"Cookies are {cfg.clrd(f'{info['age_days']}', 'yellow')} days old may be {cfg.clrd('expired', 'red')}:")
        cfg.cprint(f"\t{cfg.clrd('Use:', 'magenta')} python3{cfg.clrd(' get_cookies.py --auto', 'green')} script:")
        
    elif info['age_days'] > 20:
        cfg.cprint(f"\tCookies will {cfg.clrd('expire in approx:', 'red')} {cfg.clrd(f'{30 - info['age_days']}', 'yellow')} days:")
    else:
        cfg.cprint(f"Cookies are {cfg.clrd('good', 'yellow')} "
                f"- should be {cfg.clrd('valid', 'green')} "
                f"for approx: {cfg.clrd(f'{30 - info['age_days']}', 'green')} days:\n", end="=" * 60 + "\n")
        
    return True

if __name__ == "__main__":
    cookie_file = sys.argv[1] if len(sys.argv) > 1 else cookie_artifact
    print_cookie_file_info(cookie_file)
