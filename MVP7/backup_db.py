"""
backup_db.py
-------------
Takes a safe, point-in-time backup of partcodes.db — even while the app
is running and someone might be creating a code at that exact moment.

Why not just copy the file? SQLite's default mode writes in place, so a
plain file copy taken mid-write can capture a half-written page and give
you a corrupt backup. sqlite3's built-in `backup()` API avoids that: it
locks briefly, copies page-by-page, and always leaves you with a
consistent snapshot.

Usage (run from the app folder):
    python backup_db.py

What it does:
    1. Copies partcodes.db -> backups/partcodes_YYYY-MM-DD_HHMMSS.db
    2. Deletes backups older than KEEP_DAYS (default 30), so the folder
       doesn't grow forever
    3. Prints what it did, so you can see it worked when run by hand or
       check the output when run on a schedule

Scheduling it (so you never have to remember):
    Windows  -> Task Scheduler -> new task -> run daily ->
                action: `python C:\\path\\to\\backup_db.py`
    Linux    -> crontab -e -> add a line like:
                0 2 * * * cd /path/to/app && python3 backup_db.py

Off-machine copy (recommended): point BACKUP_DIR below at a folder that
is itself synced elsewhere (a mapped network drive, OneDrive/Drive
folder, etc.) — a backup that lives on the same machine as the original
doesn't protect you if that machine's disk fails.
"""

import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).parent / "partcodes.db")  # same file the app uses
BACKUP_DIR = Path(__file__).parent / "backups"
KEEP_DAYS = 30


def backup_once():
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH} — nothing to back up yet.")
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest_path = BACKUP_DIR / f"partcodes_{stamp}.db"

    src = sqlite3.connect(str(DB_PATH))
    dest = sqlite3.connect(str(dest_path))
    with dest:
        src.backup(dest)  # atomic, safe-to-run-while-live online backup
    src.close()
    dest.close()

    size_kb = dest_path.stat().st_size / 1024
    print(f"Backed up -> {dest_path.name} ({size_kb:.1f} KB)")

    cutoff = time.time() - KEEP_DAYS * 86400
    removed = 0
    for f in BACKUP_DIR.glob("partcodes_*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    if removed:
        print(f"Removed {removed} backup(s) older than {KEEP_DAYS} days.")


if __name__ == "__main__":
    backup_once()
