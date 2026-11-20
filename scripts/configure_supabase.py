#!/usr/bin/env python3
"""Securely test a Supabase PostgreSQL URL and save it to AlphaX .env.

Run from the project root with: python scripts/configure_supabase.py
The connection string is requested with hidden terminal input and is never printed.
The script refuses a non-empty public schema so it cannot accidentally point AlphaX
at an existing database before the one-time SQLite migration.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime
from getpass import getpass
from pathlib import Path

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
BACKUP_DIR = Path("/home/AlphaX/backups")


def normalize_supabase_uri(raw: str) -> tuple[str, str, str, int]:
    value = (raw or "").strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    try:
        url = make_url(value)
    except Exception as exc:
        raise ValueError("The pasted value is not a valid PostgreSQL connection URI.") from exc

    if url.drivername not in {"postgresql", "postgres", "postgresql+psycopg", "postgresql+psycopg2"}:
        raise ValueError("Use the PostgreSQL connection string from Supabase → Connect.")
    if not url.host or not (url.host.endswith(".pooler.supabase.com") or url.host.endswith(".supabase.co")):
        raise ValueError("The host does not look like a Supabase database host.")
    if not url.username or not url.password or not url.database:
        raise ValueError("The PostgreSQL URL must include username, password, and database name.")

    port = int(url.port or (5432 if url.host.endswith(".pooler.supabase.com") else 5432))
    if url.host.endswith(".pooler.supabase.com") and port not in {5432, 6543}:
        raise ValueError("Supabase Pooler should use port 5432 (Session) or 6543 (Transaction).")

    query = dict(url.query)
    query["sslmode"] = "require"
    # The application uses psycopg 3, with its SQLAlchemy dialect.
    app_url = url.set(drivername="postgresql+psycopg", query=query).render_as_string(hide_password=False)
    # psycopg.connect() accepts libpq's postgresql:// URI (not SQLAlchemy's driver URI).
    test_url = url.set(drivername="postgresql", query=query).render_as_string(hide_password=False)
    return app_url, test_url, url.host, port


def save_database_url(app_url: str) -> Path:
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f"Existing .env file was not found: {ENV_FILE}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"AlphaX-env-before-Supabase-{stamp}"
    shutil.copy2(ENV_FILE, backup)
    os.chmod(backup, 0o600)

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL="):
            if not replaced:
                output.append("DATABASE_URL=" + app_url)
                replaced = True
            # Skip duplicate DATABASE_URL declarations to avoid dotenv ambiguity.
        else:
            output.append(line)
    if not replaced:
        output.append("DATABASE_URL=" + app_url)

    fd, temp_name = tempfile.mkstemp(prefix=".env.alphax.", dir=str(ENV_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, ENV_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return backup


def main() -> int:
    if not ENV_FILE.is_file():
        print(f"ERROR: .env not found at {ENV_FILE}")
        return 2

    print("AlphaX → Supabase connection setup")
    print("Use Supabase Dashboard → Connect → Session Pooler (recommended, port 5432).")
    raw = getpass("Paste the Supabase PostgreSQL URI (input hidden): ").strip()
    try:
        app_url, test_url, host, port = normalize_supabase_uri(raw)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    print("Testing encrypted PostgreSQL connection...")
    try:
        import psycopg
        with psycopg.connect(test_url, connect_timeout=15) as connection:
            connection.execute("SELECT 1").fetchone()
            existing = connection.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            ).fetchall()
    except Exception as exc:
        # Do not print exception text because drivers can include connection details.
        print(f"CONNECTION FAILED: {type(exc).__name__}")
        print("The .env file was not changed. Check the URI, database password, and PythonAnywhere outbound access.")
        return 3

    if existing:
        names = ", ".join(row[0] for row in existing[:12])
        print("STOP: Supabase public schema is not empty:", names)
        print("No .env change was made. Use a new empty Supabase project for the one-time migration.")
        return 4

    try:
        backup = save_database_url(app_url)
    except Exception as exc:
        print(f"ERROR saving .env: {type(exc).__name__}")
        return 5

    print("SUPABASE CONNECTION SUCCESSFUL")
    print("Host:", host)
    print("Port:", port)
    print(".env updated: DATABASE_URL saved (password hidden).")
    print("Backup:", backup)
    print("Next: run the migration preview. Do NOT reload the website before migration is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
