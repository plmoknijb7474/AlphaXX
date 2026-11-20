#!/usr/bin/env python3
"""Safely migrate an AlphaX SQLite database into a brand-new Supabase DB.

Preview is read-only: it does not create tables or write data.
Use --apply only after reviewing the plan. The target public schema must have
no tables, so this tool never merges with or overwrites an existing database.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base, DATABASE_URL, engine as target_engine, upgrade_schema  # noqa: E402
from app import models as _models  # noqa: F401,E402 - registers model metadata

BATCH_SIZE = 250


def parse_args():
    parser = argparse.ArgumentParser(description="Safely migrate AlphaX SQLite data to Supabase PostgreSQL")
    parser.add_argument(
        "--source",
        help=("Path to the existing AlphaX SQLite .db file. If omitted, the newest "
              "/home/AlphaX/backups/AlphaX-SQLite-before-Supabase-*.db backup is selected."),
    )
    parser.add_argument("--apply", action="store_true", help="Actually create schema and copy rows; without it, preview only")
    return parser.parse_args()


def resolve_source_path(raw_source: str | None, backup_dir: Path | None = None) -> Path | None:
    if raw_source:
        return Path(raw_source).expanduser().resolve()
    backup_dir = backup_dir or Path("/home/AlphaX/backups")
    candidates = sorted(
        backup_dir.glob("AlphaX-SQLite-before-Supabase-*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0].resolve() if candidates else None


def _target_public_tables() -> list[str]:
    """Return all public tables; migration refuses any existing target schema contents."""
    inspector = inspect(target_engine)
    try:
        return sorted(inspector.get_table_names(schema="public"))
    except Exception:
        return sorted(inspector.get_table_names())


def _normalize_value(column, value: Any) -> Any:
    if value is not None and isinstance(column.type, (JSON, JSONB)) and isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _python_default(column) -> Any:
    default = column.default
    if default is None:
        return None
    value = default.arg
    if callable(value):
        try:
            return value()
        except TypeError as exc:
            raise RuntimeError(
                f"Cannot safely evaluate the Python default for column {column.table.name}.{column.name}."
            ) from exc
    return value


def _preflight_columns(source_table, target_table) -> None:
    source_names = set(source_table.c.keys())
    for column in target_table.columns:
        if column.name in source_names or column.nullable or column.server_default is not None:
            continue
        if column.default is not None or column.autoincrement is True:
            continue
        if column.primary_key and column.autoincrement:
            continue
        raise RuntimeError(
            f"Source table '{source_table.name}' lacks required target column '{column.name}' "
            "and the target schema has no safe default. Migration stopped before copying data."
        )


def main() -> int:
    args = parse_args()
    source_path = resolve_source_path(args.source)
    if source_path is None:
        print("ERROR: No SQLite backup found. Run scripts/backup_sqlite_before_supabase.py first.")
        return 2
    if not source_path.is_file():
        print(f"ERROR: SQLite source file not found: {source_path}")
        return 2
    if not DATABASE_URL.startswith("postgresql+psycopg://"):
        print("ERROR: DATABASE_URL must point to Supabase/PostgreSQL, not SQLite.")
        return 2

    source_engine = create_engine(
        f"sqlite+pysqlite:///{source_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        source_inspector = inspect(source_engine)
        source_names = set(source_inspector.get_table_names())
        if not source_names:
            print("ERROR: The SQLite database contains no tables.")
            return 2

        # Refuse any existing public table before schema creation or migration.
        # This makes the preview genuinely read-only and prevents accidental merges.
        existing_target_tables = _target_public_tables()
        if existing_target_tables:
            print("ERROR: Target database is not empty. No changes were made.")
            print("Existing tables: " + ", ".join(existing_target_tables))
            print("Use a brand-new empty Supabase project/public schema for this one-time migration. No tables were altered.")
            return 3

        planned_tables = [table for table in Base.metadata.sorted_tables if table.name in source_names]
        plan: list[tuple[str, int]] = []
        for table in planned_tables:
            with source_engine.connect() as source_conn:
                count = source_conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar_one()
            plan.append((table.name, int(count)))

        source_only = sorted(source_names - {name for name, _ in plan})
        print("AlphaX SQLite → Supabase migration plan")
        print(f"Source: {source_path}")
        print(f"Target: {target_engine.url.render_as_string(hide_password=True)}")
        print("Tables to copy:")
        for name, count in plan:
            print(f"  {name}: {count} rows")
        if source_only:
            print("Tables not in the current AlphaX schema (will not be copied): " + ", ".join(source_only))
        total_rows = sum(count for _, count in plan)
        print(f"Total rows to copy: {total_rows}")

        if not args.apply:
            print("PREVIEW ONLY. No schema or data has been written to Supabase.")
            print("After reviewing this plan and confirming the target is the intended empty project, rerun with --apply.")
            return 0

        source_meta = MetaData()
        source_meta.reflect(bind=source_engine)
        # Validate source/target column compatibility before creating any target tables.
        for target_table in planned_tables:
            _preflight_columns(source_meta.tables[target_table.name], target_table)

        # Apply starts only after explicit --apply, empty-target check and schema preflight.
        Base.metadata.create_all(target_engine)
        upgrade_schema(target_engine)
        target_inspector = inspect(target_engine)
        target_names = set(target_inspector.get_table_names())
        tables_to_copy = [table for table in planned_tables if table.name in target_names]

        copied = 0
        with source_engine.connect().execution_options(stream_results=True) as source_conn:
            with target_engine.begin() as target_conn:
                for target_table in tables_to_copy:
                    source_table = source_meta.tables[target_table.name]
                    source_columns = set(source_table.c.keys())
                    selected_columns = [source_table.c[name] for name in target_table.columns.keys() if name in source_columns]
                    if not selected_columns:
                        continue

                    result = source_conn.execute(select(*selected_columns))
                    table_copied = 0
                    while True:
                        source_rows = result.mappings().fetchmany(BATCH_SIZE)
                        if not source_rows:
                            break
                        batch: list[dict[str, Any]] = []
                        for source_row in source_rows:
                            item: dict[str, Any] = {}
                            for column in target_table.columns:
                                if column.name in source_columns:
                                    item[column.name] = _normalize_value(column, source_row[column.name])
                                elif column.default is not None:
                                    item[column.name] = _python_default(column)
                            batch.append(item)
                        target_conn.execute(target_table.insert(), batch)
                        table_copied += len(batch)
                    copied += table_copied
                    print(f"Copied {target_table.name}: {table_copied} rows")

                # Advance generated integer-id sequences past imported IDs.
                for target_table in tables_to_copy:
                    pk_cols = list(target_table.primary_key.columns)
                    if len(pk_cols) != 1 or pk_cols[0].name != "id":
                        continue
                    table_name = target_table.name.replace('"', '""')
                    quoted_table = f'public."{table_name}"'
                    target_conn.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                            f"GREATEST(COALESCE((SELECT MAX(id) FROM {quoted_table}), 1), 1), "
                            f"COALESCE((SELECT MAX(id) FROM {quoted_table}), 0) > 0)"
                        ),
                        {"table_name": quoted_table},
                    )

        print(f"SUCCESS: copied {copied} rows into Supabase.")
        print("The SQLite source was not changed. Keep it as a rollback backup until production checks pass.")
        print("Next: point DATABASE_URL to Supabase, reload AlphaX, and verify sign-in, subscriptions, user keys, prompts, and API access.")
        return 0
    except Exception as exc:
        print(f"ERROR: migration stopped: {type(exc).__name__}: {exc}")
        print("Do not delete the SQLite source or change the production DATABASE_URL until the issue is resolved.")
        return 4
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
