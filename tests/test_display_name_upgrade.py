from sqlalchemy import create_engine, inspect, text

from app import database as database_module


def test_upgrade_adds_missing_users_display_name_without_deleting_rows(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE, password_hash VARCHAR(256), active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME)"))
        conn.execute(text("INSERT INTO users (id, email, password_hash, active, created_at) VALUES (1, 'keep@example.test', 'hash', 1, CURRENT_TIMESTAMP)"))

    database_module.upgrade_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "display_name" in columns
    with engine.connect() as conn:
        row = conn.execute(text("SELECT email, username, display_name, password_hash FROM users WHERE id = 1")).one()
    assert row.email == "keep@example.test"
    assert row.username == "keep"
    assert row.display_name == ""
    assert row.password_hash == "hash"
    engine.dispose()
