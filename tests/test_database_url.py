from app.database import normalize_database_url


def test_normalize_postgres_urls_for_psycopg_and_require_ssl():
    normalized = normalize_database_url("postgresql://alpha:secret@db.example.test:5432/postgres")
    assert normalized.startswith("postgresql+psycopg://alpha:secret@db.example.test:5432/postgres")
    assert "sslmode=require" in normalized


def test_normalize_supabase_pooler_url_removes_unsafe_prepared_statement_override():
    normalized = normalize_database_url(
        "postgres://alpha:secret@aws-0-region.pooler.supabase.com:6543/postgres?sslmode=require&prepare_threshold=0"
    )
    assert normalized.startswith("postgresql+psycopg://")
    assert "sslmode=require" in normalized
    assert "prepare_threshold" not in normalized


def test_sqlite_url_is_preserved():
    assert normalize_database_url("sqlite:///./alpha.db") == "sqlite:///./alpha.db"


def test_supabase_migration_preview_does_not_create_or_upgrade_target_before_apply():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "scripts" / "migrate_sqlite_to_supabase.py").read_text()
    preview_check = script.index('if not args.apply:')
    schema_create = script.index('Base.metadata.create_all(target_engine)')
    assert preview_check < schema_create
    assert 'fetchmany(BATCH_SIZE)' in script
    assert 'mappings().all()' not in script



def test_supabase_migration_can_auto_select_latest_final_sqlite_backup(tmp_path):
    import importlib.util
    import os
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_sqlite_to_supabase.py"
    spec = importlib.util.spec_from_file_location("alphax_sqlite_supabase_migrator", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    old_backup = tmp_path / "AlphaX-SQLite-before-Supabase-old.db"
    new_backup = tmp_path / "AlphaX-SQLite-before-Supabase-new.db"
    old_backup.write_bytes(b"old")
    new_backup.write_bytes(b"new")
    os.utime(old_backup, (100, 100))
    os.utime(new_backup, (200, 200))

    assert module.resolve_source_path(None, tmp_path) == new_backup.resolve()
