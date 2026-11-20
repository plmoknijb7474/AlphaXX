from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import apply_apinex_regolo_v10_migration, apply_y5z_deepseek_reasoning_toggle_v12_migration
from app.models import ModelConfig, Provider, User, UserModelCredential, UserModelGrant
from app.services.provider_client import _openai_payload


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session(), engine


def _route(model_id, upstream_id):
    return SimpleNamespace(model_id=model_id, upstream_model_id=upstream_id, reasoning_config={})


def test_v10_routes_y5z_to_apinex_and_pro_to_regolo_preserving_max_and_user_data():
    db, engine = _db()
    google = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    openrouter = Provider(name="OpenRouter", base_url="https://openrouter.ai/api/v1", protocol="openai_compatible", active=True)
    db.add_all([google, openrouter]); db.flush()
    user = User(email="v10@example.test", username="v10-user", display_name="V10", active=True)
    db.add(user); db.flush()

    specs = [
        ("y5z-coder-pro", openrouter, "google/gemma-4-26b-a4b-it:free"),
        ("alphax-pro", google, "gemini-3.6-flash"),
        ("alphax-max", openrouter, "google/gemma-4-31b-it:free"),
    ]
    models = {}
    credentials = {}
    for public_id, provider, upstream in specs:
        model = ModelConfig(
            public_id=public_id, public_name=public_id, provider_id=provider.id,
            upstream_model_id=upstream, active=True, system_prompt=f"preserve prompt {public_id}",
            fallback_upstream_ids=["legacy-paid-fallback"], supports_reasoning=True,
            reasoning_mode="levels", reasoning_parameter="thinking_level",
            reasoning_options={"supported": True, "effort": ["minimal", "high"]},
            request_defaults={"thinking_level": "high"},
        )
        db.add(model); db.flush(); models[public_id] = model
        db.add(UserModelGrant(user_id=user.id, model_id=model.id, active=True))
        credential = UserModelCredential(user_id=user.id, model_id=model.id,
                                         secret_encrypted=f"encrypted-{public_id}", active=True)
        db.add(credential); credentials[public_id] = credential
    db.commit()

    apply_apinex_regolo_v10_migration(db)
    db.commit()

    apinex = db.scalar(select(Provider).where(Provider.name == "APInex"))
    regolo = db.scalar(select(Provider).where(Provider.name == "Regolo"))
    assert apinex.base_url == "https://api.apinex.bond/v1" and apinex.protocol == "openai_compatible" and apinex.active
    assert regolo.base_url == "https://api.regolo.ai/v1" and regolo.protocol == "openai_compatible" and regolo.active

    assert models["y5z-coder-pro"].provider_id == apinex.id
    assert models["y5z-coder-pro"].upstream_model_id == "free/deepseek-v4-pro-0813"
    assert models["alphax-pro"].provider_id == regolo.id
    assert models["alphax-pro"].upstream_model_id == "gemma4-31b"
    assert models["alphax-max"].provider_id == openrouter.id
    assert models["alphax-max"].upstream_model_id == "google/gemma-4-31b-it:free"

    for public_id in ("y5z-coder-pro", "alphax-pro"):
        model = models[public_id]
        assert model.reasoning_parameter == "reasoning_effort"
        assert model.reasoning_options["effort"] == ["low", "medium", "high"]
        assert [variant["id"] for variant in model.reasoning_variants] == ["low", "medium", "high"]
        assert model.request_defaults["reasoning_effort"] == "high"
        assert model.fallback_upstream_ids == []
        assert model.supports_tools is True and model.supports_streaming is True
        assert model.supports_vision is (public_id == "alphax-pro")
        assert model.system_prompt == f"preserve prompt {public_id}"
        assert credentials[public_id].active is False
        assert credentials[public_id].last_failure_code == "PROVIDER_CHANGED"
    assert credentials["alphax-max"].active is True
    assert all(g.active for g in db.scalars(select(UserModelGrant)).all())

    # Re-running the migration must not disable newly-added credentials for the new provider.
    for public_id in ("y5z-coder-pro", "alphax-pro"):
        db.add(UserModelCredential(user_id=user.id, model_id=models[public_id].id,
                                   secret_encrypted=f"new-{public_id}", active=True))
    db.commit()
    apply_apinex_regolo_v10_migration(db)
    db.commit()
    active_new = db.scalars(select(UserModelCredential).where(
        UserModelCredential.secret_encrypted.in_(["new-y5z-coder-pro", "new-alphax-pro"])
    )).all()
    assert len(active_new) == 2 and all(item.active for item in active_new)
    db.close(); engine.dispose()


def test_apinex_and_regolo_payloads_send_documented_reasoning_effort_levels():
    for provider_name, model_id, upstream in (
        ("APInex", "y5z-coder-pro", "free/deepseek-v4-pro-0813"),
        ("Regolo", "alphax-pro", "gemma4-31b"),
    ):
        model = ModelConfig(
            id=1, public_id=model_id, public_name=model_id, provider_id=2,
            upstream_model_id=upstream, active=True, supports_reasoning=True,
            reasoning_mode="levels", reasoning_parameter="reasoning_effort",
            reasoning_options={"supported": True, "effort": ["low", "medium", "high"]},
            request_defaults={"reasoning_effort": "high"},
        )
        for level in ("low", "medium", "high"):
            payload = _openai_payload(
                model, _route(1, upstream),
                {"model": model_id, "messages": [], "thinking_level": level},
                [{"role": "system", "content": "private system prompt"}],
                provider_name=provider_name,
            )
            assert payload["model"] == upstream
            assert payload["reasoning_effort"] == level
            assert "thinking_level" not in payload
            assert "reasoning" not in payload
            assert payload["messages"][0]["content"] == "private system prompt"

        off_alias = _openai_payload(
            model, _route(1, upstream),
            {"model": model_id, "messages": [], "alpha_reasoning": False},
            [{"role": "user", "content": "hello"}],
            provider_name=provider_name,
        )
        assert off_alias["reasoning_effort"] == "low"


def test_apinex_and_regolo_calls_use_their_exact_openai_compatible_endpoints_and_user_key(monkeypatch):
    from app.services import provider_client as pc

    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "id": "upstream-result",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "verified"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            }

    monkeypatch.setattr(pc, "decrypt_secret", lambda _: "provider-customer-key")
    for provider_name, base_url, public_id, upstream, level in (
        ("APInex", "https://api.apinex.bond/v1", "y5z-coder-pro", "free/deepseek-v4-pro-0813", "medium"),
        ("Regolo", "https://api.regolo.ai/v1", "alphax-pro", "gemma4-31b", "high"),
    ):
        captured = {}
        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()
        monkeypatch.setattr(pc.httpx, "post", fake_post)

        model = ModelConfig(
            id=7, public_id=public_id, public_name=public_id, provider_id=2,
            upstream_model_id=upstream, active=True, supports_reasoning=True,
            reasoning_mode="levels", reasoning_parameter="reasoning_effort",
            reasoning_options={"supported": True, "effort": ["low", "medium", "high"]},
            request_defaults={"reasoning_effort": "high"},
        )
        provider = SimpleNamespace(name=provider_name, protocol="openai_compatible", base_url=base_url)
        result = pc.call_route(
            _route(7, upstream), provider,
            SimpleNamespace(secret_encrypted="encrypted-user-key"), model,
            {"model": public_id, "messages": [], "reasoning_effort": level},
            [{"role": "system", "content": "model-specific prompt"}, {"role": "user", "content": "test"}],
        )
        assert captured["url"] == base_url + "/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer provider-customer-key"
        assert captured["json"]["model"] == upstream
        assert captured["json"]["reasoning_effort"] == level
        assert captured["json"]["messages"][0]["content"] == "model-specific prompt"
        assert result["model"] == public_id


def test_v12_adds_deepseek_toggle_to_y5z_only_and_is_idempotent():
    db, engine = _db()
    apinex = Provider(name="APInex", base_url="https://api.apinex.bond/v1", protocol="openai_compatible", active=True)
    regolo = Provider(name="Regolo", base_url="https://api.regolo.ai/v1", protocol="openai_compatible", active=True)
    db.add_all([apinex, regolo]); db.flush()
    y5z = ModelConfig(
        public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=apinex.id,
        upstream_model_id="free/deepseek-v4-pro-0813", active=True, system_prompt="keep prompt",
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="reasoning_effort",
        reasoning_options={"supported": True, "effort": ["low", "medium", "high"]},
        reasoning_variants=[{"id": level, "body": {"reasoning_effort": level}} for level in ("low", "medium", "high")],
        request_defaults={"reasoning_effort": "high"},
    )
    pro = ModelConfig(
        public_id="alphax-pro", public_name="AlphaX Pro", provider_id=regolo.id,
        upstream_model_id="gemma4-31b", active=True, system_prompt="keep pro prompt",
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="reasoning_effort",
        reasoning_options={"supported": True, "effort": ["low", "medium", "high"]},
    )
    db.add_all([y5z, pro]); db.commit()

    apply_y5z_deepseek_reasoning_toggle_v12_migration(db); db.commit()
    assert y5z.reasoning_options["toggle"] is True
    assert y5z.reasoning_options["effort"] == ["low", "medium", "high"]
    assert [item["id"] for item in y5z.reasoning_variants] == ["low", "medium", "high"]
    assert y5z.request_defaults["reasoning_effort"] == "high"
    assert y5z.system_prompt == "keep prompt"
    assert "toggle" not in pro.reasoning_options

    apply_y5z_deepseek_reasoning_toggle_v12_migration(db); db.commit()
    assert y5z.reasoning_options["toggle"] is True
    db.close(); engine.dispose()


def test_apinex_http_request_for_off_mode_contains_only_explicit_thinking_disable(monkeypatch):
    from app.services import provider_client as pc

    captured = {}
    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "id": "deepseek-off-test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    monkeypatch.setattr(pc, "decrypt_secret", lambda _: "apinex-customer-key")
    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()
    monkeypatch.setattr(pc.httpx, "post", fake_post)

    model = ModelConfig(
        id=91, public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=91,
        upstream_model_id="free/deepseek-v4-pro-0813", active=True,
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="reasoning_effort",
        reasoning_options={"supported": True, "toggle": True, "effort": ["low", "medium", "high"]},
        request_defaults={"reasoning_effort": "high"},
    )
    provider = SimpleNamespace(name="APInex", protocol="openai_compatible", base_url="https://api.apinex.bond/v1")
    result = pc.call_route(
        _route(91, model.upstream_model_id), provider,
        SimpleNamespace(secret_encrypted="encrypted-apinex-key"), model,
        {"model": "y5z-coder-pro", "messages": [], "reasoning_effort": "none"},
        [{"role": "system", "content": "keep admin prompt"}, {"role": "user", "content": "test"}],
    )
    assert captured["url"] == "https://api.apinex.bond/v1/chat/completions"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured["json"]
    assert captured["json"]["messages"][0]["content"] == "keep admin prompt"
    assert result["model"] == "y5z-coder-pro"
