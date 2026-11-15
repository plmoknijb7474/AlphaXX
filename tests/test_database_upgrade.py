from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from app import database as database_module
from app.database import Base
from app.models import ModelConfig, Provider, User, UserModelCredential


def test_legacy_pool_upgrade_keeps_one_primary_user_model_key_and_drops_pool(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    old_provider = Provider(name="Legacy Provider", base_url="https://fallback.invalid/v1", active=True)
    primary_provider = Provider(name="xKiro", base_url="https://api.xkiro.com/v1", active=True)
    db.add_all([old_provider, primary_provider]); db.flush()
    user = User(email="migration@example.test", display_name="Migration")
    db.add(user); db.flush()
    model = ModelConfig(public_id="legacy-model", public_name="Legacy", provider_id=old_provider.id,
                        upstream_model_id="old/default", system_prompt="Keep this prompt")
    model_without_prompt = ModelConfig(public_id="legacy-model-two", public_name="Legacy Two", provider_id=old_provider.id,
                                       upstream_model_id="old/second", system_prompt="")
    db.add_all([model, model_without_prompt]); db.commit()

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE providers ADD COLUMN api_key_encrypted TEXT"))
        conn.execute(text("UPDATE providers SET api_key_encrypted = 'legacy-provider-secret' WHERE id = :id"), {"id": old_provider.id})
        conn.execute(text("""CREATE TABLE model_routes (
            id INTEGER PRIMARY KEY, model_id INTEGER, provider_id INTEGER,
            upstream_model_id VARCHAR(200), priority INTEGER, active BOOLEAN, reasoning_config JSON
        )"""))
        conn.execute(text("""CREATE TABLE provider_credentials (
            id INTEGER PRIMARY KEY, secret_encrypted TEXT, active BOOLEAN
        )"""))
        conn.execute(text("""CREATE TABLE user_route_credential_assignments (
            id INTEGER PRIMARY KEY, user_id INTEGER, route_id INTEGER,
            credential_id INTEGER, priority INTEGER, active BOOLEAN
        )"""))
        conn.execute(text("INSERT INTO model_routes VALUES (10, :model, :provider, 'qwen/qwen3.8-max', 1, 1, '{}')"),
                     {"model": model.id, "provider": primary_provider.id})
        conn.execute(text("INSERT INTO model_routes VALUES (11, :model, :provider, 'fallback/second-model', 2, 1, '{}')"),
                     {"model": model.id, "provider": old_provider.id})
        conn.execute(text("INSERT INTO provider_credentials VALUES (100, 'encrypted-primary-key', 1)"))
        conn.execute(text("INSERT INTO provider_credentials VALUES (101, 'encrypted-fallback-key', 1)"))
        conn.execute(text("INSERT INTO user_route_credential_assignments VALUES (200, :user, 10, 100, 1, 1)"), {"user": user.id})
        conn.execute(text("INSERT INTO user_route_credential_assignments VALUES (201, :user, 11, 101, 1, 1)"), {"user": user.id})
        conn.execute(text("CREATE TABLE system_prompts (id INTEGER PRIMARY KEY, name VARCHAR(120), content TEXT, active BOOLEAN, version INTEGER, updated_at DATETIME)"))
        conn.execute(text("INSERT INTO system_prompts VALUES (1, 'Main', 'Legacy global instructions', 1, 2, CURRENT_TIMESTAMP)"))

    monkeypatch.setattr(database_module, "engine", engine)
    database_module.upgrade_schema()
    db.expire_all()
    migrated_model = db.get(ModelConfig, model.id)
    assert migrated_model.provider_id == primary_provider.id
    assert migrated_model.upstream_model_id == "qwen/qwen3.8-max"
    assert migrated_model.system_prompt == "Keep this prompt"
    migrated_model_without_prompt = db.get(ModelConfig, model_without_prompt.id)
    assert migrated_model_without_prompt.system_prompt == "Legacy global instructions"
    credential = db.scalar(select(UserModelCredential).where(
        UserModelCredential.user_id == user.id, UserModelCredential.model_id == model.id,
    ))
    assert credential.secret_encrypted == "encrypted-primary-key"
    tables = set(inspect(engine).get_table_names())
    assert not ({"model_routes", "provider_credentials", "user_route_credential_assignments", "system_prompts"} & tables)
    assert db.execute(text("SELECT api_key_encrypted FROM providers WHERE id = :id"), {"id": old_provider.id}).scalar_one() == ""
    db.close(); engine.dispose()


def test_v11_removes_per_user_model_unique_constraint_and_allows_multiple_keys(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE model_configs (id INTEGER PRIMARY KEY)"))
        conn.execute(text("""CREATE TABLE user_model_credentials (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            model_id INTEGER NOT NULL,
            secret_encrypted TEXT NOT NULL,
            active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_user_model_credential UNIQUE (user_id, model_id)
        )"""))
        conn.execute(text("INSERT INTO users VALUES (1)"))
        conn.execute(text("INSERT INTO model_configs VALUES (1)"))
        conn.execute(text("INSERT INTO user_model_credentials VALUES (1, 1, 1, 'enc-old', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    monkeypatch.setattr(database_module, "engine", engine)
    database_module.upgrade_schema()
    assert inspect(engine).get_unique_constraints("user_model_credentials") == []
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO user_model_credentials
            (id, user_id, model_id, secret_encrypted, label, priority, active,
             created_at, updated_at, failure_count, last_failure_code)
            VALUES (2, 1, 1, 'enc-second', 'Key 2', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, '')"""))
        rows = conn.execute(text("SELECT secret_encrypted FROM user_model_credentials ORDER BY id")).scalars().all()
    assert rows == ["enc-old", "enc-second"]
    engine.dispose()
