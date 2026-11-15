import json
from datetime import datetime, timedelta, timezone
from starlette.requests import Request
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet

from app.database import Base
from app.models import APIKey, ModelConfig, Provider, Subscription, User, UserModelGrant, UserModelCredential
from app.routers.customer import generate_customer_api_key, opencode_config
from app.config import settings


def _fixture_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = Session()
    user = User(email="customer@example.test", display_name="Customer", active=True)
    provider = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    db.add_all([user, provider]); db.flush()
    now = datetime.now(timezone.utc)
    subscription = Subscription(user_id=user.id, plan_id=1, status="active", starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=30))
    # This test only needs the referenced plan row for the FK.
    from app.models import Plan
    plan = Plan(name="Test", daily_token_limit=1_000_000, duration_days=30, active=True)
    db.add(plan); db.flush(); subscription.plan_id = plan.id; db.add(subscription)
    model = ModelConfig(public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=provider.id,
                        upstream_model_id="gemma-4-31b-it", active=True, system_prompt="admin only prompt",
                        supports_tools=True, supports_reasoning=True, reasoning_mode="levels",
                        reasoning_options={"supported": True, "effort": ["minimal", "high"]},
                        reasoning_variants=[{"id": "thinking-off", "body": {"thinking_level": "minimal"}},
                                            {"id": "thinking-on", "body": {"thinking_level": "high"}}])
    db.add(model); db.flush()
    db.add_all([
        UserModelGrant(user_id=user.id, model_id=model.id, active=True),
        UserModelCredential(user_id=user.id, model_id=model.id, secret_encrypted="encrypted-upstream-secret", active=True),
    ])
    db.commit()
    return db, engine, user


def _request(user_id):
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/account/api-key/generate", "raw_path": b"/account/api-key/generate",
        "query_string": b"", "headers": [(b"host", b"alphax.test")],
        "server": ("alphax.test", 443), "client": ("testclient", 50000),
        "session": {"user_id": user_id, "customer_csrf": "test-csrf"},
    }
    return Request(scope)


def test_customer_can_generate_multiple_independent_alphax_keys(monkeypatch):
    db, engine, user = _fixture_db()
    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())
    request = _request(user.id)
    generate_customer_api_key(request, csrf="test-csrf", key_name="OpenCode Desktop", db=db)
    generate_customer_api_key(request, csrf="test-csrf", key_name="Laptop", db=db)
    keys = db.scalars(select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.id)).all()
    assert len(keys) == 2
    assert all(item.active for item in keys)
    assert [item.name for item in keys] == ["OpenCode Desktop", "Laptop"]
    assert all(item.secret_delivery_encrypted for item in keys)
    db.close(); engine.dispose()


def test_downloaded_opencode_config_contains_only_fake_aliases_and_v2_schema(monkeypatch):
    db, engine, user = _fixture_db()
    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())
    generate_customer_api_key(_request(user.id), csrf="test-csrf", key_name="OpenCode", db=db)
    request = _request(user.id)
    request.scope["path"] = "/account/opencode-config"
    request.scope["raw_path"] = b"/account/opencode-config"
    response = opencode_config(request, db=db)
    config = json.loads(response.body)
    assert config["providers"]["alphax"]["package"] == "@opencode/ai/providers/openai-compatible"
    assert config["providers"]["alphax"]["settings"]["baseURL"].endswith("/v1")
    assert set(config["providers"]["alphax"]["models"]) == {"y5z-coder-pro"}
    text = json.dumps(config).lower()
    assert "gemma-4-31b-it" not in text
    assert "google ai studio" not in text and "generativelanguage.googleapis.com" not in text
    assert "admin only prompt" not in text
    assert "minimal" in text and "high" in text
    db.close(); engine.dispose()


def test_opencode_config_exposes_per_model_reasoning_variants_without_internal_names(monkeypatch):
    db, engine, user = _fixture_db()
    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())
    google = db.scalar(select(Provider).where(Provider.name == "Google AI Studio"))
    gemini = ModelConfig(
        public_id="alphax-pro", public_name="AlphaX Pro", provider_id=google.id,
        upstream_model_id="gemini-3.6-flash", active=True, system_prompt="private AlphaX Pro prompt",
        supports_tools=True, supports_reasoning=True, reasoning_mode="levels",
        reasoning_options={"supported": True, "effort": ["minimal", "low", "medium", "high"]},
        reasoning_variants=[
            {"id": level, "body": {"reasoning_effort": level}}
            for level in ("minimal", "low", "medium", "high")
        ],
    )
    db.add(gemini); db.flush()
    db.add_all([
        UserModelGrant(user_id=user.id, model_id=gemini.id, active=True),
        UserModelCredential(user_id=user.id, model_id=gemini.id, secret_encrypted="secret-gemini", active=True),
    ])
    db.commit()
    generate_customer_api_key(_request(user.id), csrf="test-csrf", key_name="OpenCode", db=db)
    request = _request(user.id)
    request.scope["path"] = "/account/opencode-config"
    request.scope["raw_path"] = b"/account/opencode-config"
    config = json.loads(opencode_config(request, db=db).body)
    models = config["providers"]["alphax"]["models"]
    assert set(models) == {"y5z-coder-pro", "alphax-pro"}
    assert [v["id"] for v in models["alphax-pro"]["variants"]] == ["minimal", "low", "medium", "high"]
    rendered = json.dumps(config).lower()
    assert "gemini-3.6-flash" not in rendered
    assert "google ai studio" not in rendered
    assert "private alphax pro prompt" not in rendered
    db.close(); engine.dispose()


def test_opencode_config_exposes_gemma4_two_state_thinking_only(monkeypatch):
    db, engine, user = _fixture_db()
    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())
    google = db.scalar(select(Provider).where(Provider.name == "Google AI Studio"))
    gemma = ModelConfig(
        public_id="alphax-max", public_name="AlphaX Max", provider_id=google.id,
        upstream_model_id="gemma-4-26b-a4b-it", active=True, system_prompt="private Gemma prompt",
        supports_tools=True, supports_vision=True, supports_reasoning=True, reasoning_mode="levels",
        reasoning_options={"supported": True, "effort": ["minimal", "high"]},
        reasoning_variants=[
            {"id": "thinking-off", "body": {"thinking_level": "minimal"}},
            {"id": "thinking-on", "body": {"thinking_level": "high"}},
        ],
    )
    db.add(gemma); db.flush()
    db.add_all([
        UserModelGrant(user_id=user.id, model_id=gemma.id, active=True),
        UserModelCredential(user_id=user.id, model_id=gemma.id, secret_encrypted="secret-gemma", active=True),
    ])
    db.commit()
    generate_customer_api_key(_request(user.id), csrf="test-csrf", key_name="OpenCode Gemma", db=db)
    request = _request(user.id)
    request.scope["path"] = "/account/opencode-config"
    request.scope["raw_path"] = b"/account/opencode-config"
    config = json.loads(opencode_config(request, db=db).body)
    entry = config["providers"]["alphax"]["models"]["alphax-max"]
    assert entry["capabilities"]["reasoning"]["effort"] == ["minimal", "high"]
    assert entry["capabilities"]["tools"] is True
    assert [variant["id"] for variant in entry["variants"]] == ["thinking-off", "thinking-on"]
    text = json.dumps(config).lower()
    assert "gemma-4-26b-a4b-it" not in text
    assert "google ai studio" not in text
    assert "private gemma prompt" not in text
    db.close(); engine.dispose()
