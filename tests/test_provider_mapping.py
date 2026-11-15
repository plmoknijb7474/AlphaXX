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
