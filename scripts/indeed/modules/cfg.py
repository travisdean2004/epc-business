#!/usr/bin/env python
# -*- config: utf-8 -*-

from rich import print as colored

"""SOC: keeps base urls refs"""

def get_base_url(jb_board: str) -> str:
    if jb_board == "indeed":
        return "https://www.indeed.com"
    elif jb_board == "glassdoor":
        return "https://www.glassdoor.com"
    elif jb_board == "dice":
        return "https://www.dice.com/jobs"
    else:
        raise ValueError(f"Invalid board: {jb_board}")

def clrd(text: str, color: str = "red") -> str:
    return f"[bold {color}]{text}[/bold {color}]"

def cprint(*args, **kwargs):
    colored(*args, **kwargs)

if __name__ == "__main__":
    print(get_base_url(jb_board="indeed"))
    print(get_base_url(jb_board="glassdoor"))
    print(get_base_url(jb_board="dice"))
