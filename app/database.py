from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

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


def upgrade_schema(bind=None):
    """Upgrade old AlphaX schemas on SQLite or PostgreSQL and retire the old shared-key pool."""
    target_engine = bind or engine
    dialect = target_engine.dialect.name
    datetime_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
    bool_default = "FALSE" if dialect == "postgresql" else "0"
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
            "users": {"password_hash": "VARCHAR(256)"},
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
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

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
