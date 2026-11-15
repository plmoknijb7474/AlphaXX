from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ModelConfig, Provider, User, UserModelCredential
from app.services import provider_client as pc


def _db_with_keys(fallback=None):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = Session()
    user = User(email="multi@example.test", display_name="Multi")
    provider = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    db.add_all([user, provider]); db.flush()
    model = ModelConfig(
        public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=provider.id,
        upstream_model_id="gemma-4-26b-a4b-it", fallback_upstream_ids=fallback or [],
        system_prompt="Admin-owned prompt", active=True, supports_tools=True,
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="thinking_level", request_defaults={"thinking_level": "high"},
    )
    db.add(model); db.flush()
    first = UserModelCredential(user_id=user.id, model_id=model.id, secret_encrypted="encrypted-key-1", label="Key 1", priority=0, active=True)
    second = UserModelCredential(user_id=user.id, model_id=model.id, secret_encrypted="encrypted-key-2", label="Key 2", priority=1, active=True)
    db.add_all([first, second]); db.commit()
    return db, engine, user, model, first, second


def test_completion_tries_next_customer_key_and_cools_down_the_failed_one(monkeypatch):
    db, engine, user, model, first, second = _db_with_keys()
    attempts = []

    def fake_call(route, provider, credential, selected_model, request_data, messages):
        attempts.append((route.upstream_model_id, credential.secret_encrypted))
        if credential.secret_encrypted == "encrypted-key-1":
            raise pc.ProviderFailure(retryable=True, status_code=429, allow_model_fallback=True)
        return {"model": selected_model.public_id, "ok": True}

    monkeypatch.setattr(pc, "call_route", fake_call)
    result = pc.complete_for_user(db, user.id, model, {"model": model.public_id}, [{"role": "user", "content": "hi"}])
    assert result == {"model": "y5z-coder-pro", "ok": True}
    assert attempts == [
        ("gemma-4-26b-a4b-it", "encrypted-key-1"),
        ("gemma-4-26b-a4b-it", "encrypted-key-2"),
    ]
    ordered = pc._user_model_route(db, user.id, model)[2]
    assert ordered[0].id == second.id  # the just-failed key is temporarily deprioritized
    db.close(); engine.dispose()


def test_primary_overload_uses_configured_coder_fallback_with_same_user_keys(monkeypatch):
    fallback_id = "gemma-4-31b-it"
    db, engine, user, model, first, second = _db_with_keys([fallback_id])
    attempts = []

    def fake_call(route, provider, credential, selected_model, request_data, messages):
        attempts.append((route.upstream_model_id, credential.secret_encrypted))
        if route.upstream_model_id == "gemma-4-26b-a4b-it":
            raise pc.ProviderFailure(retryable=True, status_code=529, allow_model_fallback=True)
        return {"model": selected_model.public_id, "served_by": "fallback"}

    monkeypatch.setattr(pc, "call_route", fake_call)
    result = pc.complete_for_user(db, user.id, model, {"model": model.public_id}, [{"role": "user", "content": "write code"}])
    assert result == {"model": "y5z-coder-pro", "served_by": "fallback"}
    assert attempts == [
        ("gemma-4-26b-a4b-it", "encrypted-key-1"),
        ("gemma-4-26b-a4b-it", "encrypted-key-2"),
        (fallback_id, "encrypted-key-1"),
    ]
    db.close(); engine.dispose()


def test_stream_retries_next_key_only_before_sending_any_chunk(monkeypatch):
    db, engine, user, model, first, second = _db_with_keys()
    attempts = []

    def fake_stream(route, provider, credential, selected_model, request_data, messages, stats):
        attempts.append(credential.secret_encrypted)
        if credential.secret_encrypted == "encrypted-key-1":
            raise pc.ProviderFailure(retryable=True, status_code=429, allow_model_fallback=True)
        yield 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(pc, "stream_route", fake_stream)
    stats = {"text": "", "reasoning": ""}
    chunks = list(pc.stream_for_user(db, user.id, model, {"model": model.public_id, "stream": True}, [{"role": "user", "content": "hi"}], stats))
    assert attempts == ["encrypted-key-1", "encrypted-key-2"]
    assert len(chunks) == 2
    db.close(); engine.dispose()


def test_auth_failure_tries_next_key_but_never_another_customers_key(monkeypatch):
    db, engine, user, model, first, second = _db_with_keys()
    other_user = User(email="other@example.test", display_name="Other")
    db.add(other_user); db.flush()
    other_key = UserModelCredential(
        user_id=other_user.id, model_id=model.id,
        secret_encrypted="other-customers-secret", label="Other Key", priority=0, active=True,
    )
    db.add(other_key); db.commit()

    attempts = []
    def fake_call(route, provider, credential, selected_model, request_data, messages):
        attempts.append(credential.secret_encrypted)
        if credential.secret_encrypted == "encrypted-key-1":
            raise pc.ProviderFailure(retryable=True, status_code=401)
        return {"model": selected_model.public_id, "ok": True}

    monkeypatch.setattr(pc, "call_route", fake_call)
    result = pc.complete_for_user(db, user.id, model, {"model": model.public_id}, [{"role": "user", "content": "hi"}])
    assert result["ok"] is True
    assert attempts == ["encrypted-key-1", "encrypted-key-2"]
    assert "other-customers-secret" not in attempts
    db.close(); engine.dispose()
