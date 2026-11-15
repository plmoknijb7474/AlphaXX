from sqlalchemy import create_engine, inspect, text

from app.database import Base, upgrade_schema


def test_schema_upgrade_reconciles_all_existing_tables_additively():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # Representative deployed legacy tables from before the customer portal update.
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(256), created_at DATETIME)"))
        conn.execute(text("INSERT INTO users (id, email, password_hash, created_at) VALUES (9, 'legacy.name@example.test', 'keep-this-hash', CURRENT_TIMESTAMP)"))
        conn.execute(text("CREATE TABLE plans (id INTEGER PRIMARY KEY, name VARCHAR(80), daily_token_limit INTEGER, active BOOLEAN)"))
        conn.execute(text("INSERT INTO plans (id, name, daily_token_limit, active) VALUES (4, 'Legacy Plan', 12345, 1)"))
        conn.execute(text("CREATE TABLE purchase_orders (id INTEGER PRIMARY KEY, user_id INTEGER, plan_id INTEGER, amount VARCHAR(40))"))
        conn.execute(text("INSERT INTO purchase_orders (id, user_id, plan_id, amount) VALUES (3, 9, 4, '9.99')"))
        conn.execute(text("CREATE TABLE api_keys (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(100), prefix VARCHAR(24), key_hash VARCHAR(64), active BOOLEAN, created_at DATETIME)"))

    upgrade_schema(engine)

    inspector = inspect(engine)
    for table_name in ("users", "plans", "purchase_orders", "api_keys"):
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        expected = set(Base.metadata.tables[table_name].columns.keys())
        assert expected.issubset(actual), f"{table_name} missing: {sorted(expected - actual)}"

    with engine.connect() as conn:
        user = conn.execute(text("SELECT username, password_hash, active FROM users WHERE id = 9")).one()
        plan = conn.execute(text("SELECT name, daily_token_limit, duration_days, currency FROM plans WHERE id = 4")).one()
        order = conn.execute(text("SELECT amount, payment_method, status FROM purchase_orders WHERE id = 3")).one()
    assert user.username == "legacy.name"
    assert user.password_hash == "keep-this-hash"
    assert user.active in (1, True)
    assert (plan.name, plan.daily_token_limit, plan.duration_days, plan.currency) == ("Legacy Plan", 12345, 30, "USDT")
    assert order.amount == "9.99"
    engine.dispose()
