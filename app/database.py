from __future__ import annotations

import re
import json
import logging
from datetime import date, datetime
from sqlalchemy import (
    Boolean, Date, DateTime, Integer, JSON, String, Text,
    Index, create_engine, inspect, text
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger("alphax.database")

from .config import settings


def normalize_database_url(raw_url: str) -> str:
    """Normalize Supabase/PostgreSQL URLs for the installed psycopg 3 driver."""
    value = (raw_url or "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is empty")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    elif value.startswith("postgresql+psycopg2://"):
        value = "postgresql+psycopg://" + value[len("postgresql+psycopg2://"):]

    url = make_url(value)
    if url.drivername.startswith("postgresql"):
        query = {key: value for key, value in dict(url.query).items() if key != "prepare_threshold"}
        query.setdefault("sslmode", "require")
        url = url.set(drivername="postgresql+psycopg").set(query=query)
    return url.render_as_string(hide_password=False)


DATABASE_URL = normalize_database_url(settings.database_url)

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
else:
    # Supabase transaction poolers work more reliably when psycopg's automatic
    # server-side prepared statements are disabled. SSL is enforced by URL normalization.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=3,
        max_overflow=2,
        connect_args={"connect_timeout": 15, "prepare_threshold": None},
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _quote_identifier(target_engine, value: str) -> str:
    return target_engine.dialect.identifier_preparer.quote(value)


def _column_default_sql(column, dialect_name: str) -> str | None:
    """Return a portable SQL default for adding a column to a populated legacy table."""
    if column.server_default is not None:
        return str(column.server_default.arg)

    default = column.default
    if default is not None:
        value = default.arg
        if callable(value):
            if isinstance(column.type, JSON):
                try:
                    sample = value()
                except Exception:
                    sample = None
                if isinstance(sample, list):
                    return "'[]'"
                if isinstance(sample, dict):
                    return "'{}'"
            if isinstance(column.type, (Date, DateTime)):
                return "CURRENT_DATE" if isinstance(column.type, Date) and not isinstance(column.type, DateTime) else "CURRENT_TIMESTAMP"
        else:
            if isinstance(value, bool):
                return ("TRUE" if value else "FALSE") if dialect_name == "postgresql" else ("1" if value else "0")
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, (datetime, date)):
                return "CURRENT_TIMESTAMP" if isinstance(value, datetime) else "CURRENT_DATE"
            if isinstance(column.type, JSON):
                return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'"
            if isinstance(value, str):
                return "'" + value.replace("'", "''") + "'"

    if isinstance(column.type, Boolean):
        return "FALSE" if dialect_name == "postgresql" else "0"
    if isinstance(column.type, Integer):
        return "0"
    if isinstance(column.type, JSON):
        # SQLAlchemy JSON fields in AlphaX are either arrays or objects.
        return "'[]'" if column.key in {"public_skills", "public_highlights", "reasoning_variants", "fallback_upstream_ids", "requested_model_ids"} else "'{}'"
    if isinstance(column.type, DateTime):
        return "CURRENT_TIMESTAMP"
    if isinstance(column.type, Date):
        return "CURRENT_DATE"
    if isinstance(column.type, (String, Text)):
        return "''"
    return None


def _reconcile_model_columns(conn, target_engine) -> list[str]:
    """Add all columns known to current ORM models to existing legacy tables.

    create_all() creates new tables but intentionally does not alter existing ones.
    Earlier releases only migrated a short allow-list of columns, which left other
    customer/admin actions able to fail with UndefinedColumn. This additive pass
    brings every existing table up to the current ORM column set without dropping
    or rewriting existing user data.
    """
    # Import lazily to avoid database <-> models import cycles.
    from . import models as _models  # noqa: F401

    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    missing_primary_keys: list[str] = []
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        current_columns = {item["name"] for item in inspect(conn).get_columns(table.name)}
        for column in table.columns:
            if column.name in current_columns:
                continue
            if column.primary_key:
                missing_primary_keys.append(f"{table.name}.{column.name}")
                continue

            type_sql = column.type.compile(dialect=target_engine.dialect)
            default_sql = _column_default_sql(column, target_engine.dialect.name)
            # A required field with no safe default (especially a foreign key) is
            # added nullable for legacy rows. New ORM writes still supply it.
            can_be_not_null = not column.nullable and (default_sql is not None) and not column.foreign_keys
            # SQLite disallows adding a populated-table column with a non-constant
            # default such as CURRENT_TIMESTAMP. Add it nullable, then backfill it.
            sqlite_dynamic_default = (
                target_engine.dialect.name == "sqlite"
                and default_sql in {"CURRENT_TIMESTAMP", "CURRENT_DATE"}
            )
            if sqlite_dynamic_default:
                nullable_sql = ""
                default_clause = ""
            else:
                nullable_sql = " NOT NULL" if can_be_not_null else ""
                default_clause = f" DEFAULT {default_sql}" if default_sql is not None else ""
            table_sql = _quote_identifier(target_engine, table.name)
            column_sql = _quote_identifier(target_engine, column.name)
            conn.execute(text(
                f"ALTER TABLE {table_sql} ADD COLUMN {column_sql} {type_sql}{nullable_sql}{default_clause}"
            ))
            if sqlite_dynamic_default:
                conn.execute(text(
                    f"UPDATE {table_sql} SET {column_sql} = {default_sql} WHERE {column_sql} IS NULL"
                ))
            added.append(f"{table.name}.{column.name}")
            current_columns.add(column.name)

    if missing_primary_keys:
        raise RuntimeError(
            "Legacy database is missing primary-key columns that cannot be safely added automatically: "
            + ", ".join(missing_primary_keys)
        )

    if added:
        logger.info("AlphaX database compatibility migration added %d missing columns: %s", len(added), ", ".join(added))
    else:
        logger.info("AlphaX database schema already contains all current ORM columns")
    return added


def _reconcile_model_indexes(conn) -> None:
    """Restore ORM indexes after legacy usernames and data have been normalized."""
    from . import models as _models  # noqa: F401
    existing_tables = set(inspect(conn).get_table_names())
    # Recreate ORM indexes that may have been skipped when create_all() encountered
    # an older, already-existing table. Use savepoints so duplicate legacy data in
    # one optional unique index cannot roll back the column repairs.
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        current_columns = {item["name"] for item in inspect(conn).get_columns(table.name)}
        existing_indexes = inspect(conn).get_indexes(table.name)
        existing_index_names = {item.get("name") for item in existing_indexes}
        existing_unique_sets = {
            frozenset(item.get("column_names") or [])
            for item in inspect(conn).get_unique_constraints(table.name)
        }
        existing_unique_sets.update(
            frozenset(item.get("column_names") or [])
            for item in existing_indexes if item.get("unique")
        )
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            if not all(col.name in current_columns for col in index.columns):
                continue
            if index.name in existing_index_names:
                continue
            colset = frozenset(col.name for col in index.columns)
            if index.unique and colset in existing_unique_sets:
                continue
            try:
                with conn.begin_nested():
                    index.create(conn, checkfirst=True)
                existing_index_names.add(index.name)
                if index.unique:
                    existing_unique_sets.add(colset)
            except Exception as exc:
                logger.warning("Could not restore index %s on %s: %s", index.name, table.name, exc)

        for constraint in table.constraints:
            if constraint.__class__.__name__ != "UniqueConstraint":
                continue
            names = [col.name for col in constraint.columns]
            colset = frozenset(names)
            if not names or not all(name in current_columns for name in names) or colset in existing_unique_sets:
                continue
            index_name = constraint.name or f"uq_{table.name}_{'_'.join(names)}"
            if index_name in existing_index_names:
                continue
            try:
                with conn.begin_nested():
                    Index(index_name, *[table.c[name] for name in names], unique=True).create(conn, checkfirst=True)
                existing_index_names.add(index_name)
                existing_unique_sets.add(colset)
            except Exception as exc:
                logger.warning("Could not restore unique constraint %s on %s: %s", index_name, table.name, exc)



def upgrade_schema(bind=None):
    """Upgrade old AlphaX schemas on SQLite or PostgreSQL and retire the old shared-key pool."""
    target_engine = bind or engine
    dialect = target_engine.dialect.name
    datetime_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
    bool_default = "FALSE" if dialect == "postgresql" else "0"
    bool_true = "TRUE" if dialect == "postgresql" else "1"
    with target_engine.begin() as conn:
        additions = {
            "providers": {
                "protocol": "VARCHAR(40) NOT NULL DEFAULT 'openai_compatible'",
            },
            "model_configs": {
                "supports_reasoning": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
                "supports_vision": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
                "reasoning_mode": "VARCHAR(24) NOT NULL DEFAULT 'none'",
                "reasoning_parameter": "VARCHAR(80) NOT NULL DEFAULT 'reasoning'",
                "reasoning_options": "JSON",
                "request_defaults": "JSON",
                "reasoning_variants": "JSON",
                "fallback_upstream_ids": "JSON",
                "public_description": "TEXT NOT NULL DEFAULT ''",
                "public_skills": "JSON",
                "public_highlights": "JSON",
                "public_image": "VARCHAR(500) NOT NULL DEFAULT ''",
                "system_prompt": "TEXT NOT NULL DEFAULT ''",
            },
            "user_model_credentials": {
                "label": "VARCHAR(80) NOT NULL DEFAULT 'Key'",
                "priority": "INTEGER NOT NULL DEFAULT 0",
                "last_attempt_at": datetime_type,
                "last_failure_at": datetime_type,
                "failure_count": "INTEGER NOT NULL DEFAULT 0",
                "last_failure_code": "VARCHAR(24) NOT NULL DEFAULT ''",
            },
            "users": {
                "username": "VARCHAR(80)",
                "display_name": "VARCHAR(120) NOT NULL DEFAULT ''",
                "password_hash": "VARCHAR(256)",
                # Some older/custom Supabase schemas have username and display_name
                # but are missing the active flag expected by customer login/API auth.
                # Default existing rows to enabled so this additive migration preserves access.
                "active": f"BOOLEAN NOT NULL DEFAULT {bool_true}",
            },
            "api_keys": {"secret_delivery_encrypted": "TEXT"},
            "purchase_orders": {
                "issued_api_key_id": "INTEGER",
                "payment_method": "VARCHAR(32) NOT NULL DEFAULT 'binance'",
                "subscription_id": "INTEGER",
            },
        }
        tables = set(inspect(conn).get_table_names())
        # Old Provider rows could carry provider-wide secrets. The new architecture
        # never reads them; blank them before old pool tables are retired.
        if "providers" in tables:
            provider_columns = {col["name"] for col in inspect(conn).get_columns("providers")}
            if "api_key_encrypted" in provider_columns:
                conn.execute(text("UPDATE providers SET api_key_encrypted = ''"))

        for table, columns in additions.items():
            if table not in tables:
                continue
            existing = {col["name"] for col in inspect(conn).get_columns(table)}
            added_users_active = table == "users" and "active" not in existing
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            if table == "users":
                # Carry forward a legacy is_active flag if this database used that name.
                if added_users_active and "is_active" in existing:
                    conn.execute(text("UPDATE users SET active = is_active"))
                # A nullable legacy active column should not silently lock customers out.
                conn.execute(text(f"UPDATE users SET active = {bool_true} WHERE active IS NULL"))

        # Reconcile every mapped ORM column, not only the historical short allow-list.
        # This prevents pages and form actions from failing later on older Supabase schemas.
        _reconcile_model_columns(conn, target_engine)

        # New customer accounts use usernames. Preserve old accounts by deriving a
        # stable username from the local part of their former email address.
        tables = set(inspect(conn).get_table_names())
        if "users" in tables:
            user_columns = {col["name"] for col in inspect(conn).get_columns("users")}
            email_expr = "email" if "email" in user_columns else "NULL"
            rows = conn.execute(text(f"SELECT id, {email_expr} AS email, username FROM users ORDER BY id")).mappings().all()
            used: set[str] = set()
            planned_names: list[tuple[int, str, str | None]] = []
            for row in rows:
                existing_username = str(row["username"] or "").strip().lower()
                if existing_username:
                    base = re.sub(r"[^a-z0-9_.-]+", "", existing_username).strip("._-")[:24]
                else:
                    email = str(row["email"] or "")
                    local = email.split("@", 1)[0].lower()
                    base = re.sub(r"[^a-z0-9_.-]+", "", local).strip("._-")[:24]
                if len(base) < 3:
                    base = f"user{row['id']}"
                candidate = base
                suffix = 1
                while candidate.lower() in used:
                    tail = str(suffix)
                    candidate = f"{base[:30-len(tail)]}{tail}"
                    suffix += 1
                planned_names.append((row["id"], candidate, row["username"]))
                used.add(candidate.lower())

            # Existing deployments may already have a case-sensitive unique index.
            # Move rows through collision-free temporary names before lowercasing;
            # otherwise changing `Alpha` to `alpha` could collide with another row.
            current_names = {str(row["username"] or "").lower() for row in rows}
            temp_names: list[tuple[int, str, str]] = []
            for user_id, candidate, old_name in planned_names:
                if candidate == old_name:
                    continue
                temp = f"alphaxmigration{user_id}"
                suffix = 1
                while temp.lower() in current_names or temp.lower() in used:
                    temp = f"alphaxmigration{user_id}{suffix}"
                    suffix += 1
                current_names.add(temp.lower())
                temp_names.append((user_id, temp, candidate))
            for user_id, temp, _candidate in temp_names:
                conn.execute(text("UPDATE users SET username = :username WHERE id = :id"),
                             {"username": temp, "id": user_id})
            for user_id, _temp, candidate in temp_names:
                conn.execute(text("UPDATE users SET username = :username WHERE id = :id"),
                             {"username": candidate, "id": user_id})
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))

        # Remove legacy uniqueness on (user_id, model_id) so each pair can own
        # several encrypted credentials. Existing direct credentials are retained.
        tables = set(inspect(conn).get_table_names())
        if "user_model_credentials" in tables:
            unique_constraints = inspect(conn).get_unique_constraints("user_model_credentials")
            pair_constraints = [
                item for item in unique_constraints
                if set(item.get("column_names") or []) == {"user_id", "model_id"}
            ]
            if dialect == "postgresql":
                for item in pair_constraints:
                    if item.get("name"):
                        safe_name = item["name"].replace('"', '""')
                        conn.execute(text(f'ALTER TABLE user_model_credentials DROP CONSTRAINT IF EXISTS "{safe_name}"'))
            elif dialect == "sqlite" and pair_constraints:
                columns = {col["name"] for col in inspect(conn).get_columns("user_model_credentials")}
                conn.execute(text("""CREATE TABLE user_model_credentials_multi (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    model_id INTEGER NOT NULL REFERENCES model_configs(id),
                    secret_encrypted TEXT NOT NULL,
                    label VARCHAR(80) NOT NULL DEFAULT 'Key',
                    priority INTEGER NOT NULL DEFAULT 0,
                    active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_attempt_at DATETIME,
                    last_used_at DATETIME,
                    last_failure_at DATETIME,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_failure_code VARCHAR(24) NOT NULL DEFAULT ''
                )"""))
                desired = ["id", "user_id", "model_id", "secret_encrypted", "label", "priority", "active", "created_at", "updated_at", "last_attempt_at", "last_used_at", "last_failure_at", "failure_count", "last_failure_code"]
                defaults = {
                    "label": "'Key'", "priority": "0", "last_attempt_at": "NULL",
                    "last_failure_at": "NULL", "failure_count": "0", "last_failure_code": "''",
                    "created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP", "active": "1",
                    "last_used_at": "NULL",
                }
                select_expr = [name if name in columns else f"{defaults.get(name, 'NULL')} AS {name}" for name in desired]
                conn.execute(text(f"INSERT INTO user_model_credentials_multi ({', '.join(desired)}) SELECT {', '.join(select_expr)} FROM user_model_credentials"))
                conn.execute(text("DROP TABLE user_model_credentials"))
                conn.execute(text("ALTER TABLE user_model_credentials_multi RENAME TO user_model_credentials"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_model_credentials_user_id ON user_model_credentials (user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_model_credentials_model_id ON user_model_credentials (model_id)"))

        # Migrate the former primary route into ModelConfig's direct provider/model fields.
        tables = set(inspect(conn).get_table_names())
        if "model_routes" in tables and "model_configs" in tables:
            conn.execute(text("""
                UPDATE model_configs
                SET provider_id = (SELECT mr.provider_id FROM model_routes mr
                                  WHERE mr.model_id = model_configs.id AND mr.active = TRUE
                                  ORDER BY mr.priority ASC, mr.id ASC LIMIT 1),
                    upstream_model_id = (SELECT mr.upstream_model_id FROM model_routes mr
                                         WHERE mr.model_id = model_configs.id AND mr.active = TRUE
                                         ORDER BY mr.priority ASC, mr.id ASC LIMIT 1)
                WHERE EXISTS (SELECT 1 FROM model_routes mr
                              WHERE mr.model_id = model_configs.id AND mr.active = TRUE)
            """))

        # Preserve explicitly assigned legacy primary-route keys before retiring old Pool tables.
        tables = set(inspect(conn).get_table_names())
        required = {"user_route_credential_assignments", "provider_credentials", "model_routes", "user_model_credentials"}
        if required.issubset(tables):
            conn.execute(text("""
                INSERT INTO user_model_credentials
                    (user_id, model_id, secret_encrypted, label, priority, active, created_at, updated_at, failure_count, last_failure_code)
                SELECT a.user_id, r.model_id, c.secret_encrypted, 'Key 1', 0, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, ''
                FROM user_route_credential_assignments a
                JOIN model_routes r ON r.id = a.route_id
                JOIN provider_credentials c ON c.id = a.credential_id
                WHERE r.active = TRUE AND a.active = TRUE AND c.active = TRUE
                  AND r.priority = (SELECT MIN(r2.priority) FROM model_routes r2
                                    WHERE r2.model_id = r.model_id AND r2.active = TRUE)
                  AND a.id = (SELECT a2.id
                              FROM user_route_credential_assignments a2
                              JOIN provider_credentials c2 ON c2.id = a2.credential_id
                              WHERE a2.user_id = a.user_id AND a2.route_id = a.route_id
                                AND a2.active = TRUE AND c2.active = TRUE
                              ORDER BY a2.priority ASC, a2.id ASC LIMIT 1)
                  AND NOT EXISTS (SELECT 1 FROM user_model_credentials u
                                  WHERE u.user_id = a.user_id AND u.model_id = r.model_id)
            """))

        # Copy the former global prompt into each model only when its own prompt is empty.
        tables = set(inspect(conn).get_table_names())
        if "system_prompts" in tables and "model_configs" in tables:
            legacy_prompt_columns = {col["name"] for col in inspect(conn).get_columns("system_prompts")}
            if {"content", "active"}.issubset(legacy_prompt_columns):
                conn.execute(text("""
                    UPDATE model_configs
                    SET system_prompt = (
                        SELECT content FROM system_prompts
                        WHERE active = TRUE
                        ORDER BY version DESC, updated_at DESC, id DESC LIMIT 1
                    )
                    WHERE COALESCE(system_prompt, '') = ''
                      AND EXISTS (SELECT 1 FROM system_prompts WHERE active = TRUE AND COALESCE(content, '') <> '')
                """))

        # Retire legacy shared-key Pool and global-prompt tables only after data migration.
        for table in ("user_route_credential_assignments", "model_routes", "provider_credentials", "system_prompts"):
            if table in set(inspect(conn).get_table_names()):
                conn.execute(text(f"DROP TABLE {table}"))

        # Restore indexes only after usernames have been normalized and legacy tables migrated.
        _reconcile_model_indexes(conn)
