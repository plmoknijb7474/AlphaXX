from sqlalchemy import create_engine, inspect, text
from app.database import upgrade_schema


def test_username_upgrade_backfills_legacy_users_and_keeps_records():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE, password_hash VARCHAR(256), active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME)"))
        conn.execute(text("INSERT INTO users (id, email, password_hash, active, created_at) VALUES (1, 'sam@example.com', 'hash-a', 1, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO users (id, email, password_hash, active, created_at) VALUES (2, 'sam@other.example', 'hash-b', 1, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO users (id, email, password_hash, active, created_at) VALUES (3, '!!!@example.com', 'hash-c', 1, CURRENT_TIMESTAMP)"))

    upgrade_schema(engine)

    cols = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "username" in cols
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, username, password_hash FROM users ORDER BY id")).all()
    assert rows[0].username == "sam"
    assert rows[1].username != "sam"
    assert rows[2].username == "user3"
    assert [row.password_hash for row in rows] == ["hash-a", "hash-b", "hash-c"]
    engine.dispose()


def test_username_upgrade_normalizes_existing_case_duplicates():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), username VARCHAR(80), password_hash VARCHAR(256), active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME)"))
        conn.execute(text("INSERT INTO users (id, email, username, password_hash, active, created_at) VALUES (1, 'a@example.test', 'Alpha', 'hash-1', 1, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO users (id, email, username, password_hash, active, created_at) VALUES (2, 'b@example.test', 'alpha', 'hash-2', 1, CURRENT_TIMESTAMP)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))
    upgrade_schema(engine)
    with engine.connect() as conn:
        names = conn.execute(text("SELECT username FROM users ORDER BY id")).scalars().all()
    assert names[0] == "alpha"
    assert names[1] == "alpha1"
    engine.dispose()
