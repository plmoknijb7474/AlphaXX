import base64
import json
from types import SimpleNamespace

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import ModelConfig, Provider, User, UserModelCredential
from app.services import provider_client as pc


PNG_1X1 = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")
).decode()


def model(public_id="y5z-coder-pro", reasoning_mode="toggle", supports_vision=False):
    return ModelConfig(
        id=1, public_id=public_id, public_name="Public Alpha Model", provider_id=1,
        upstream_model_id="private-upstream-model", active=True, supports_tools=True,
        supports_streaming=True, supports_vision=supports_vision,
        supports_reasoning=reasoning_mode != "none", reasoning_mode=reasoning_mode,
        request_defaults={}, reasoning_options={}, reasoning_variants=[],
    )


def route(protocol="openai_compatible", reasoning_config=None):
    return SimpleNamespace(id=1, model_id=1, provider_id=1, upstream_model_id="private-upstream-model",
                           reasoning_config=reasoning_config or {})


def test_gemma4_reasoning_maps_to_supported_google_thinking_levels():
    m = ModelConfig(
        id=1, public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=1,
        upstream_model_id="gemma-4-31b-it", active=True, supports_tools=True,
        supports_streaming=True, supports_vision=True, supports_reasoning=True,
        reasoning_mode="levels", reasoning_parameter="thinking_level",
        reasoning_options={"supported": True, "effort": ["minimal", "high"]},
        request_defaults={"thinking_level": "high"},
    )
    r = route("google_genai")
    for level in ("minimal", "high"):
        body, _ = pc._google_request(m, r, {"thinking_level": level}, [
            {"role": "system", "content": "ADMIN PROMPT"},
            {"role": "user", "content": "Solve this"},
        ], "google-test-key")
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == level
        assert body["systemInstruction"]["parts"][0]["text"] == "ADMIN PROMPT"


def test_google_adapter_translates_data_url_image_and_admin_system_prompt():
    messages = [
        {"role": "system", "content": "ADMIN CENTRAL PROMPT"},
        {"role": "user", "content": [{"type": "text", "text": "Describe this"}, {"type": "image_url", "image_url": {"url": PNG_1X1}}]},
    ]
    contents, system = pc._google_contents(messages)
    assert system == "ADMIN CENTRAL PROMPT"
    inline = contents[0]["parts"][1]["inlineData"]
    assert inline["mimeType"] == "image/png"
    assert base64.b64decode(inline["data"]).startswith(bytes.fromhex("89504e47"))


def test_google_adapter_rejects_remote_image_url_instead_of_fetching_unsafe_url():
    with pytest.raises(pc.ProviderFailure) as exc:
        pc._google_contents([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "http://127.0.0.1/private"}}]}])
    assert exc.value.retryable is False


def test_google_adapter_maps_tools_and_tool_choice():
    m = model("alphax-max", "toggle", True)
    r = route("google_genai")
    body, _ = pc._google_request(m, r, {
        "tools": [{"type": "function", "function": {"name": "read_file", "description": "Read a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
    }, [{"role": "system", "content": "ADMIN PROMPT"}, {"role": "user", "content": "Read a file"}], "secret")
    assert body["systemInstruction"]["parts"][0]["text"] == "ADMIN PROMPT"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "read_file"
    assert body["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] == ["read_file"]


def test_google_adapter_preserves_tool_call_result_roundtrip():
    messages = [
        {"role": "system", "content": "ADMIN PROMPT"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"text":"hello"}'},
    ]
    contents, system = pc._google_contents(messages)
    assert system == "ADMIN PROMPT"
    assert contents[0]["parts"][0]["functionCall"]["name"] == "read_file"
    assert contents[1]["parts"][0]["functionResponse"]["name"] == "read_file"
    assert contents[1]["parts"][0]["functionResponse"]["response"] == {"text": "hello"}


class FakeResponse:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self.lines


class FakeStreamContext:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *args):
        return False


class FakeClient:
    response = None
    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        self.last_request = (method, url, kwargs)
        return FakeStreamContext(self.response)


def test_openai_compatible_stream_forwards_incremental_chunks_and_redacts_provider(monkeypatch):
    first = {"id": "upstream-id", "model": "private-upstream-model", "provider": "secret-provider", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    second = {"id": "upstream-id", "model": "private-upstream-model", "provider": "secret-provider", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]}
    reasoning = {"id": "upstream-id", "model": "private-upstream-model", "choices": [{"index": 0, "delta": {"reasoning_content": "thinking"}, "finish_reason": None}]}
    FakeClient.response = FakeResponse(["data: " + json.dumps(x) for x in [first, second, reasoning]] + ["data: [DONE]"])
    monkeypatch.setattr(pc.httpx, "Client", FakeClient)
    monkeypatch.setattr(pc, "decrypt_secret", lambda _: "provider-secret")
    m = model()
    stats = {"text": "", "reasoning": "", "usage": {}}
    events = list(pc.stream_route(route(), SimpleNamespace(protocol="openai_compatible", base_url="https://provider.invalid/v1"), SimpleNamespace(secret_encrypted="enc"), m, {"alpha_reasoning": True}, [{"role": "system", "content": "ADMIN PROMPT"}], stats))
    decoded = [json.loads(x[6:]) for x in events if x.startswith("data: {")]
    assert len(decoded) == 3
    assert all(item["model"] == "y5z-coder-pro" for item in decoded)
    assert all("provider" not in item for item in decoded)
    assert stats["text"] == "Hello"
    assert stats["reasoning"] == "thinking"
    assert "[DONE]" in events[-1]


def test_google_stream_emits_openai_chunks_and_tool_calls(monkeypatch):
    first = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Answer"}]}}]}
    second = {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": "read_file", "args": {"path": "a.py"}}}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3, "totalTokenCount": 8}}
    FakeClient.response = FakeResponse(["data: " + json.dumps(first), "data: " + json.dumps(second)])
    monkeypatch.setattr(pc.httpx, "Client", FakeClient)
    monkeypatch.setattr(pc, "decrypt_secret", lambda _: "google-secret")
    m = model("alphax-max", "toggle", True)
    stats = {"text": "", "reasoning": "", "usage": {}}
    events = list(pc.stream_route(route("google_genai"), SimpleNamespace(protocol="google_genai", base_url="https://generativelanguage.googleapis.com/v1beta"), SimpleNamespace(secret_encrypted="enc"), m, {"tools": [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]}, [{"role": "system", "content": "ADMIN PROMPT"}, {"role": "user", "content": "Use tool"}], stats))
    decoded = [json.loads(x[6:]) for x in events if x.startswith("data: {") and '"choices"' in x]
    assert any(d["choices"][0]["delta"].get("content") == "Answer" for d in decoded)
    assert any(d["choices"][0]["delta"].get("tool_calls") for d in decoded)
    assert decoded[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert stats["usage"]["total_tokens"] == 8
    assert events[-1] == "data: [DONE]\n\n"


def test_one_user_model_key_is_used_and_failed_key_is_not_rotated(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    provider = Provider(name="test-provider", base_url="https://provider.invalid/v1", active=True)
    user = User(email="key-owner@example.test", display_name="Key owner")
    db.add_all([provider, user]); db.flush()
    configured_model = ModelConfig(
        public_id="test-model", public_name="Test Model", provider_id=provider.id,
        upstream_model_id="vendor/test-model", system_prompt="Private model prompt", active=True,
    )
    db.add(configured_model); db.flush()
    db.add(UserModelCredential(user_id=user.id, model_id=configured_model.id,
                               secret_encrypted="encrypted-single-key", active=True))
    db.commit()
    attempts = []

    def fail_once(route_obj, provider_obj, credential, model_obj, request_data, messages):
        attempts.append((credential.secret_encrypted, route_obj.upstream_model_id))
        raise pc.ProviderFailure("upstream unavailable", retryable=True)

    monkeypatch.setattr(pc, "call_route", fail_once)
    monkeypatch.setattr(pc, "decrypt_secret", lambda value: "decrypted-test-key")
    with pytest.raises(pc.ProviderFailure):
        pc.complete_for_user(db, user.id, configured_model, {}, [{"role": "user", "content": "hi"}])
    assert attempts == [("encrypted-single-key", "vendor/test-model")]
    assert len(attempts) == 1
    db.close(); engine.dispose()


def test_google_gemma_y5z_prompt_and_thinking_are_forwarded():
    m = ModelConfig(
        id=1, public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=1,
        upstream_model_id="gemma-4-31b-it", active=True, supports_tools=True,
        supports_streaming=True, supports_vision=True, supports_reasoning=True,
        reasoning_mode="levels", reasoning_parameter="thinking_level",
        reasoning_options={"supported": True, "effort": ["minimal", "high"]},
        request_defaults={"thinking_level": "high"},
    )
    body, _ = pc._google_request(m, route("google_genai"), {"thinking_level": "high"}, [
        {"role": "system", "content": "CENTRAL ADMIN PROMPT"},
        {"role": "user", "content": "Solve this"},
    ], "google-test-key")
    assert body["systemInstruction"]["parts"][0]["text"] == "CENTRAL ADMIN PROMPT"
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"


def test_openai_payload_keeps_central_prompt_on_stream_and_tool_requests():
    incoming = [
        {"role": "system", "content": "CENTRAL ADMIN PROMPT"},
        {"role": "user", "content": "Use the tool"},
    ]
    payload = pc._openai_payload(
        model("y5z-coder-pro"), route(),
        {"tools": [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]},
        incoming, stream=True,
    )
    assert payload["stream"] is True
    assert payload["messages"][0]["content"] == "CENTRAL ADMIN PROMPT"
    assert payload["tools"][0]["function"]["name"] == "read_file"
