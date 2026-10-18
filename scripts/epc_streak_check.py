#!/usr/bin/env python3
"""
EPC Streak/Warning System
Checks for reps who haven't checked in for 2+ consecutive working days.
Logs warnings to the DB and prints flagged reps for delivery.
"""

import sqlite3
import os
from datetime import date, timedelta

DB_PATH = os.path.expanduser("~/.hermes/epc_reps.db")


def get_working_days_back(n=5):
    """Return last N working days (Mon-Fri) before today."""
    days = []
    d = date.today() - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:  # 0=Mon, 4=Fri
            days.append(d.isoformat())
        d -= timedelta(days=1)
    return days


def check_streaks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT id, name, telegram_username FROM reps WHERE active = 1")
    reps = c.fetchall()

    working_days = get_working_days_back(5)
    today = date.today().isoformat()
    flagged = []

    for rep_id, name, username in reps:
        # Check last 2 working days for missing check-ins
        last_two = working_days[:2]
        c.execute(
            "SELECT date FROM daily_checkins WHERE rep_id = ? AND date IN (?, ?)",
            (rep_id, last_two[0], last_two[1])
        )
        found_dates = {row[0] for row in c.fetchall()}
        missed = [d for d in last_two if d not in found_dates]

        if len(missed) >= 2:
            flagged.append((rep_id, name, username, missed))
            # Log warning if not already logged today
            c.execute(
                "SELECT id FROM warnings WHERE rep_id = ? AND date = ?",
                (rep_id, today)
            )
            if not c.fetchone():
                c.execute(
                    "INSERT INTO warnings (rep_id, date, reason, action_taken) VALUES (?, ?, ?, ?)",
                    (rep_id, today,
                     f"No check-in for {len(missed)} consecutive working days ({', '.join(missed)})",
                     "Auto-flagged by streak checker — review required")
                )

    conn.commit()

    if flagged:
        print("⚠️ EPC STREAK ALERT — GHOSTS ON THE ROSTER\n")
        print(f"Missing 2+ consecutive check-ins as of {today}:\n")
        for rep_id, name, username, missed in flagged:
            print(f"  🚨 {name} ({username}) — missed: {', '.join(missed)}")
        print(f"\nTotal flagged: {len(flagged)}")
        print("Action required: Call them, warn them, or cut them.")
    else:
        print(f"✅ All reps accounted for as of {today}. No streak violations.")

    conn.close()


if __name__ == "__main__":
    check_streaks()
