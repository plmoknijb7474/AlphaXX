from sqlalchemy import create_engine, inspect, text

from app.database import upgrade_schema


def test_upgrade_adds_missing_users_active_column_and_preserves_existing_account():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # Matches the deployed failure: active is absent but username fields exist.
        conn.execute(text("""CREATE TABLE users (
            id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE,
            username VARCHAR(80), display_name VARCHAR(120) NOT NULL DEFAULT '',
            password_hash VARCHAR(256), created_at DATETIME
        )"""))
        conn.execute(text("""INSERT INTO users
            (id, email, username, display_name, password_hash, created_at)
            VALUES (7, 'legacy@example.test', 'alphax-admin', 'Legacy', 'existing-hash', CURRENT_TIMESTAMP)"""))

    upgrade_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {"email", "username", "display_name", "password_hash", "active", "created_at"}.issubset(columns)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, email, username, display_name, password_hash, active FROM users WHERE id = 7")).one()
    assert (row.id, row.email, row.username, row.display_name, row.password_hash) == (
        7, "legacy@example.test", "alphax-admin", "Legacy", "existing-hash"
    )
    assert row.active in (1, True)
    engine.dispose()


def test_upgrade_copies_legacy_is_active_values():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE users (
            id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE,
            username VARCHAR(80), display_name VARCHAR(120) NOT NULL DEFAULT '',
            password_hash VARCHAR(256), is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME
        )"""))
        conn.execute(text("""INSERT INTO users
            (id, email, username, display_name, password_hash, is_active, created_at)
            VALUES (1, 'disabled@example.test', 'disabled_user', '', 'hash', 0, CURRENT_TIMESTAMP)"""))

    upgrade_schema(engine)
    with engine.connect() as conn:
        active = conn.execute(text("SELECT active FROM users WHERE id = 1")).scalar_one()
    assert active in (0, False)
    engine.dispose()
