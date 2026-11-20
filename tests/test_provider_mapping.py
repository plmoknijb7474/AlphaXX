from types import SimpleNamespace
from app.models import ModelConfig
from app.services.provider_client import _openai_payload, _google_request


def route(model_id, provider_id, upstream="gemini-3.6-flash"):
    return SimpleNamespace(model_id=model_id, provider_id=provider_id, upstream_model_id=upstream, reasoning_config={})


def test_openai_compatible_generic_route_keeps_prompt_and_upstream_alias_mapping():
    model = ModelConfig(
        id=1, public_id="alphax-pro", public_name="AlphaX Pro", provider_id=2,
        upstream_model_id="generic-test-model", active=True,
        supports_reasoning=True, reasoning_mode="levels",
        request_defaults={"temperature": 0.2},
    )
    payload = _openai_payload(model, route(1, 2, "generic-test-model"), {
        "model": "alphax-pro", "messages": [], "temperature": 0.7, "stream": True,
    }, [{"role": "system", "content": "Model-specific Alpha prompt"}])
    assert payload["model"] == "generic-test-model"
    assert payload["temperature"] == 0.7
    assert payload["messages"][0]["content"] == "Model-specific Alpha prompt"
    assert payload["stream"] is False


def test_gemini_36_flash_maps_all_official_reasoning_efforts():
    model = ModelConfig(
        id=4, public_id="alphax-pro", public_name="AlphaX Pro", provider_id=3,
        upstream_model_id="gemini-3.6-flash", active=True, supports_reasoning=True,
        reasoning_mode="levels", request_defaults={"thinking_level": "medium"},
        reasoning_options={"supported": True, "effort": ["minimal", "low", "medium", "high"]},
    )
    route_obj = route(4, 3, "gemini-3.6-flash")
    for level in ("minimal", "low", "medium", "high"):
        body, _ = _google_request(model, route_obj, {"thinking_level": level}, [
            {"role": "system", "content": "Model prompt"},
            {"role": "user", "content": "Hello"},
        ], "test-key")
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == level


def test_gemma4_31b_and_26b_map_only_minimal_and_high_thinking_levels():
    for public_id, upstream_id in (("y5z-coder-pro", "gemma-4-26b-a4b-it"), ("alphax-max", "gemma-4-31b-it")):
        model = ModelConfig(
            id=5, public_id=public_id, public_name=public_id, provider_id=3,
            upstream_model_id=upstream_id, active=True, supports_reasoning=True,
            reasoning_mode="levels", reasoning_parameter="thinking_level",
            reasoning_options={"supported": True, "effort": ["minimal", "high"]},
            request_defaults={"thinking_level": "high"},
        )
        route_obj = route(5, 3, upstream_id)
        for level in ("minimal", "high"):
            body, _ = _google_request(model, route_obj, {"thinking_level": level}, [
                {"role": "system", "content": "Model prompt"},
                {"role": "user", "content": "Hello"},
            ], "test-key")
            assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == level
            assert body["systemInstruction"]["parts"][0]["text"] == "Model prompt"


def test_openrouter_gemma_minimal_disables_reasoning_and_high_uses_effort():
    model = ModelConfig(
        id=20, public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=9,
        upstream_model_id="google/gemma-4-26b-a4b-it:free", active=True,
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="thinking_level",
        reasoning_options={"supported": True, "effort": ["minimal", "high"]},
        request_defaults={"thinking_level": "high", "temperature": 0.2},
    )
    route_obj = route(20, 9, "google/gemma-4-26b-a4b-it:free")

    minimal = _openai_payload(
        model, route_obj, {"model": "y5z-coder-pro", "messages": [], "thinking_level": "minimal"},
        [{"role": "system", "content": "Keep the model prompt"}], provider_name="OpenRouter",
    )
    assert minimal["model"] == "google/gemma-4-26b-a4b-it:free"
    assert minimal["reasoning"] == {"effort": "none"}
    assert "thinking_level" not in minimal
    assert "reasoning_effort" not in minimal
    assert minimal["temperature"] == 0.2

    high = _openai_payload(
        model, route_obj, {"model": "y5z-coder-pro", "messages": [], "thinking_level": "high"},
        [{"role": "system", "content": "Keep the model prompt"}], provider_name="OpenRouter",
    )
    assert high["reasoning"] == {"effort": "high"}
    assert "thinking_level" not in high
    assert high["messages"][0]["content"] == "Keep the model prompt"


def test_openrouter_call_uses_openrouter_endpoint_bearer_key_and_mapped_reasoning(monkeypatch):
    from types import SimpleNamespace
    from app.services import provider_client as pc

    captured = {}
    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "id": "upstream-id", "model": "google/gemma-4-26b-a4b-it:free",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(pc, "decrypt_secret", lambda _: "sk-or-v1-test-token")
    monkeypatch.setattr(pc.httpx, "post", fake_post)
    model = ModelConfig(
        id=31, public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=12,
        upstream_model_id="google/gemma-4-26b-a4b-it:free", active=True,
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="thinking_level",
        reasoning_options={"supported": True, "effort": ["minimal", "high"]},
        request_defaults={"thinking_level": "high"},
    )
    provider = SimpleNamespace(
        name="OpenRouter", protocol="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
    )
    route_obj = route(31, 12, model.upstream_model_id)
    result = pc.call_route(
        route_obj, provider, SimpleNamespace(secret_encrypted="encrypted"), model,
        {"model": "y5z-coder-pro", "messages": [], "thinking_level": "high"},
        [{"role": "system", "content": "Alpha-owned model prompt"}, {"role": "user", "content": "hi"}],
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-v1-test-token"
    assert captured["json"]["model"] == "google/gemma-4-26b-a4b-it:free"
    assert captured["json"]["reasoning"] == {"effort": "high"}
    assert "thinking_level" not in captured["json"]
    assert captured["json"]["messages"][0]["content"] == "Alpha-owned model prompt"
    assert result["model"] == "y5z-coder-pro"


def test_apinex_deepseek_reasoning_toggle_sends_real_disabled_and_enabled_modes():
    model = ModelConfig(
        id=82, public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=82,
        upstream_model_id="free/deepseek-v4-pro-0813", active=True,
        supports_reasoning=True, reasoning_mode="levels", reasoning_parameter="reasoning_effort",
        reasoning_options={"supported": True, "toggle": True, "effort": ["low", "medium", "high"]},
        request_defaults={"reasoning_effort": "high"},
    )
    route_obj = route(82, 82, model.upstream_model_id)

    for level in ("low", "medium", "high"):
        payload = _openai_payload(
            model, route_obj, {"model": "y5z-coder-pro", "messages": [], "reasoning_effort": level},
            [{"role": "user", "content": "test"}], provider_name="APInex",
        )
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == level
        assert "alpha_reasoning" not in payload

    off_by_none = _openai_payload(
        model, route_obj, {"model": "y5z-coder-pro", "messages": [], "reasoning_effort": "none"},
        [{"role": "user", "content": "test"}], provider_name="APInex",
    )
    assert off_by_none["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in off_by_none

    off_by_switch = _openai_payload(
        model, route_obj, {"model": "y5z-coder-pro", "messages": [], "reasoning_effort": "high", "alpha_reasoning": False},
        [{"role": "user", "content": "test"}], provider_name="APInex",
    )
    assert off_by_switch["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in off_by_switch
