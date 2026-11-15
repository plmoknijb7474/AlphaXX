#!/usr/bin/env python3
"""Create a consistent SQLite + .env backup before switching to Supabase.

Run from the AlphaX project root while DATABASE_URL still points to SQLite:
    python scripts/backup_sqlite_before_supabase.py
The migration utility automatically selects the newest generated SQLite backup.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.database import DATABASE_URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
BACKUP_DIR = Path("/home/AlphaX/backups")


def main() -> int:
    if not ENV_FILE.is_file():
        print(f"ERROR: .env not found: {ENV_FILE}")
        return 2
    url = make_url(DATABASE_URL)
    if not url.drivername.startswith("sqlite"):
        print("ERROR: DATABASE_URL is not SQLite. Run this BEFORE configure_supabase.py.")
        return 2
    if not url.database:
        print("ERROR: SQLite path is empty.")
        return 2

    source = Path(url.database).expanduser()
    if not source.is_absolute():
        source = (PROJECT_ROOT / source).resolve()
    else:
        source = source.resolve()
    if not source.is_file():
        print(f"ERROR: SQLite database not found: {source}")
        return 2

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_backup = BACKUP_DIR / f"AlphaX-SQLite-before-Supabase-{stamp}.db"
    env_backup = BACKUP_DIR / f"AlphaX-env-before-Supabase-{stamp}.env"

    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
            integrity = src.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                print("ERROR: SQLite integrity_check did not return ok. No backup was accepted.")
                return 3
            with sqlite3.connect(db_backup) as dst:
                src.backup(dst)
        shutil.copy2(ENV_FILE, env_backup)
        db_backup.chmod(0o600)
        env_backup.chmod(0o600)
    except Exception as exc:
        print(f"ERROR: backup failed: {type(exc).__name__}")
        return 4

    print("SQLITE BACKUP SUCCESSFUL")
    print("SQLITE_BACKUP=" + str(db_backup))
    print("ENV_BACKUP=" + str(env_backup))
    print("The migration command automatically selects the newest SQLite backup above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
