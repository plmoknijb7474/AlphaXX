from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import apply_alphax_max_gemini36_v11_migration
from app.models import ModelConfig, Provider, User, UserModelCredential, UserModelGrant
from app.services.provider_client import _google_request


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session(), engine


def test_v11_routes_only_alphax_max_to_google_gemini_and_preserves_other_models_and_data():
    db, engine = _db()
    google = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    openrouter = Provider(name="OpenRouter", base_url="https://openrouter.ai/api/v1", protocol="openai_compatible", active=True)
    apinex = Provider(name="APInex", base_url="https://api.apinex.bond/v1", protocol="openai_compatible", active=True)
    regolo = Provider(name="Regolo", base_url="https://api.regolo.ai/v1", protocol="openai_compatible", active=True)
    db.add_all([google, openrouter, apinex, regolo]); db.flush()
    user = User(email="v11@example.test", username="v11-user", display_name="V11", active=True)
    db.add(user); db.flush()

    y5z = ModelConfig(public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=apinex.id,
        upstream_model_id="free/deepseek-v4-pro-0813", active=True, system_prompt="keep y5z prompt",
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="reasoning_effort",
        reasoning_options={"supported": True, "effort": ["low", "medium", "high"]},
        request_defaults={"reasoning_effort": "high"})
    pro = ModelConfig(public_id="alphax-pro", public_name="AlphaX Pro", provider_id=regolo.id,
        upstream_model_id="gemma4-31b", active=True, system_prompt="keep pro prompt",
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="reasoning_effort",
        reasoning_options={"supported": True, "effort": ["low", "medium", "high"]},
        request_defaults={"reasoning_effort": "high"})
    max_model = ModelConfig(public_id="alphax-max", public_name="AlphaX Max", provider_id=openrouter.id,
        upstream_model_id="google/gemma-4-31b-it:free", active=True, system_prompt="keep max prompt",
        fallback_upstream_ids=["paid-fallback"], supports_reasoning=True, reasoning_mode="levels",
        reasoning_parameter="thinking_level", reasoning_options={"supported": True, "effort": ["minimal", "high"]},
        request_defaults={"thinking_level": "high"})
    db.add_all([y5z, pro, max_model]); db.flush()

    old_google_key = UserModelCredential(user_id=user.id, model_id=max_model.id,
        secret_encrypted="encrypted-old-google-key", active=False, last_failure_code="PROVIDER_CHANGED")
    openrouter_key = UserModelCredential(user_id=user.id, model_id=max_model.id,
        secret_encrypted="encrypted-openrouter-key", active=True)
    db.add_all([old_google_key, openrouter_key,
        UserModelGrant(user_id=user.id, model_id=max_model.id, active=True)])
    db.commit()

    apply_alphax_max_gemini36_v11_migration(db)
    db.commit()

    assert max_model.provider_id == google.id
    assert max_model.upstream_model_id == "gemini-3.6-flash"
    assert max_model.fallback_upstream_ids == []
    assert max_model.supports_reasoning and max_model.reasoning_mode == "levels"
    assert max_model.reasoning_parameter == "thinking_level"
    assert max_model.reasoning_options["effort"] == ["minimal", "low", "medium", "high"]
    assert [v["id"] for v in max_model.reasoning_variants] == ["minimal", "low", "medium", "high"]
    assert max_model.request_defaults["thinking_level"] == "medium"
    assert max_model.supports_tools and max_model.supports_streaming and max_model.supports_vision
    assert max_model.system_prompt == "keep max prompt"
    assert old_google_key.active is True and old_google_key.last_failure_code == ""
    assert openrouter_key.active is False and openrouter_key.last_failure_code == "PROVIDER_CHANGED"
    assert db.scalar(select(UserModelGrant).where(UserModelGrant.model_id == max_model.id)).active is True
    assert y5z.provider_id == apinex.id and y5z.upstream_model_id == "free/deepseek-v4-pro-0813"
    assert pro.provider_id == regolo.id and pro.upstream_model_id == "gemma4-31b"

    # Idempotence: newly supplied Google credentials must not be disabled on a repeated call.
    new_google_key = UserModelCredential(user_id=user.id, model_id=max_model.id,
        secret_encrypted="encrypted-new-google-key", active=True)
    db.add(new_google_key); db.commit()
    apply_alphax_max_gemini36_v11_migration(db); db.commit()
    assert new_google_key.active is True
    db.close(); engine.dispose()


def test_google_gemini36_request_sends_selected_native_thinking_level():
    model = ModelConfig(
        id=7, public_id="alphax-max", public_name="AlphaX Max", provider_id=3,
        upstream_model_id="gemini-3.6-flash", active=True, supports_reasoning=True,
        reasoning_mode="levels", reasoning_parameter="thinking_level",
        reasoning_options={"supported": True, "effort": ["minimal", "low", "medium", "high"]},
        request_defaults={"thinking_level": "medium"},
    )
    route = SimpleNamespace(reasoning_config={})
    for level in ("minimal", "low", "medium", "high"):
        body, api_key = _google_request(model, route, {"thinking_level": level},
            [{"role": "system", "content": "Admin system prompt"},
             {"role": "user", "content": "Test"}], "google-test-key")
        assert api_key == "google-test-key"
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == level
        assert body["systemInstruction"]["parts"][0]["text"] == "Admin system prompt"
        assert body["contents"][0]["parts"][0]["text"] == "Test"


def test_alphax_max_call_uses_google_ai_studio_native_endpoint_and_api_key(monkeypatch):
    from app.services import provider_client as pc

    captured = {}

    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "candidates": [{"content": {"role": "model", "parts": [{"text": "Gemini Max is online."}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 5, "totalTokenCount": 9},
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(pc, "decrypt_secret", lambda _: "google-ai-studio-test-key")
    monkeypatch.setattr(pc.httpx, "post", fake_post)
    google = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    model = ModelConfig(
        id=90, public_id="alphax-max", public_name="AlphaX Max", provider_id=90,
        upstream_model_id="gemini-3.6-flash", active=True, supports_reasoning=True,
        reasoning_mode="levels", reasoning_parameter="thinking_level",
        reasoning_options={"supported": True, "effort": ["minimal", "low", "medium", "high"]},
        request_defaults={"thinking_level": "medium"},
    )
    route = SimpleNamespace(model_id=90, upstream_model_id="gemini-3.6-flash", reasoning_config={})
    result = pc.call_route(
        route, google, SimpleNamespace(secret_encrypted="encrypted-google-key"), model,
        {"model": "alphax-max", "messages": [{"role": "user", "content": "Hi"}], "thinking_level": "high"},
        [{"role": "system", "content": "AlphaX Max system prompt"}, {"role": "user", "content": "Hi"}],
    )

    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    assert captured["params"] == {"key": "google-ai-studio-test-key"}
    assert captured["json"]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"
    assert captured["json"]["systemInstruction"]["parts"][0]["text"] == "AlphaX Max system prompt"
    assert result["model"] == "alphax-max"
    assert result["choices"][0]["message"]["content"] == "Gemini Max is online."
