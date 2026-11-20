"""Provider adapters for Alpha.

Supports OpenAI-compatible chat completions and Google's native Gemini API.
The public Alpha model alias is always written back to responses. Upstream provider
names, model IDs, URLs and error bodies are never forwarded to customers.
"""
from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ModelConfig, Provider, UserModelCredential
from ..security import decrypt_secret

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
KEY_RETRY_STATUS = {401, 402, 403}
MODEL_FALLBACK_STATUS = RETRYABLE_STATUS | {404}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_INLINE_IMAGE_BYTES = 15 * 1024 * 1024


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        public_message: str = "The selected Alpha model is temporarily unavailable",
        retryable: bool = True,
        status_code: int | None = None,
        allow_model_fallback: bool = False,
    ):
        super().__init__(public_message)
        self.retryable = retryable
        self.status_code = status_code
        self.allow_model_fallback = allow_model_fallback


def _deep_merge(left: dict, right: dict) -> dict:
    result = dict(left or {})
    for key, value in (right or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _openai_payload(model: ModelConfig, route, request_data: dict, messages: list[dict], stream: bool = False, provider_name: str = "") -> dict:
    defaults = dict(model.request_defaults or {})
    route_defaults = dict(route.reasoning_config or {})
    request_fields = {
        k: v for k, v in request_data.items()
        if k not in {"model", "messages", "alpha_reasoning", "variant", "stream", "stream_options"}
    }
    payload = _deep_merge(defaults, route_defaults)
    payload = _deep_merge(payload, request_fields)
    payload["model"] = route.upstream_model_id
    payload["messages"] = messages
    payload["stream"] = bool(stream)

    # OpenRouter exposes a unified reasoning object. AlphaX keeps the same
    # customer-facing two-state Gemma control, then translates it here:
    # minimal = thinking disabled; high = high reasoning effort.
    if provider_name.strip().lower() == "openrouter":
        for key in ("thinking_level", "reasoning_effort", "reasoning", "thinking", "alpha_reasoning"):
            payload.pop(key, None)
        if model.supports_reasoning and model.reasoning_mode == "levels":
            options = model.reasoning_options or {}
            allowed = options.get("effort") if isinstance(options, dict) else None
            allowed = [str(x).strip().lower() for x in allowed] if isinstance(allowed, list) else ["minimal", "high"]
            defaults_for_reasoning = model.request_defaults or {}
            default_effort = (defaults_for_reasoning.get(model.reasoning_parameter)
                              or defaults_for_reasoning.get("thinking_level")
                              or defaults_for_reasoning.get("reasoning_effort")
                              or ("high" if "high" in allowed else allowed[-1]))
            requested = (request_data.get(model.reasoning_parameter)
                         or request_data.get("thinking_level")
                         or request_data.get("reasoning_effort")
                         or default_effort)
            if request_data.get("alpha_reasoning") is False:
                requested = "minimal" if "minimal" in allowed else default_effort
            effort = str(requested).strip().lower()
            if effort not in allowed:
                effort = str(default_effort).strip().lower()
            if effort not in allowed:
                effort = allowed[-1] if allowed else "high"
            if effort == "minimal":
                # OpenRouter accepts "none" as the explicit reasoning-off level.
                # This preserves AlphaX's existing Gemma minimal = thinking off behavior.
                payload["reasoning"] = {"effort": "none"}
            else:
                payload["reasoning"] = {"effort": effort}
    elif provider_name.strip().lower() in {"apinex", "regolo"}:
        # APInex and Regolo expose the OpenAI-compatible `reasoning_effort`
        # field directly (unlike OpenRouter's {reasoning: {effort: ...}} shape).
        # APInex DeepSeek additionally supports the native `thinking.type`
        # switch; other routes remain levels-only unless configured otherwise.
        for key in ("thinking_level", "reasoning_effort", "reasoning", "thinking", "alpha_reasoning"):
            payload.pop(key, None)
        if model.supports_reasoning and model.reasoning_mode == "levels":
            options = model.reasoning_options or {}
            allowed = options.get("effort") if isinstance(options, dict) else None
            allowed = [str(x).strip().lower() for x in allowed if str(x).strip()] if isinstance(allowed, list) else []
            if allowed:
                defaults_for_reasoning = model.request_defaults or {}
                parameter = str(model.reasoning_parameter or "reasoning_effort").strip()
                default_effort = (defaults_for_reasoning.get(parameter)
                                  or defaults_for_reasoning.get("reasoning_effort")
                                  or defaults_for_reasoning.get("thinking_level")
                                  or allowed[-1])
                requested = (request_data.get(parameter)
                             or request_data.get("reasoning_effort")
                             or request_data.get("thinking_level"))
                nested_reasoning = request_data.get("reasoning")
                if not requested and isinstance(nested_reasoning, dict):
                    requested = nested_reasoning.get("effort")

                # DeepSeek V4 Pro on APInex exposes a separate thinking-mode
                # switch. `none`/OFF must disable reasoning, not downgrade it
                # to the least-intensive enabled level.
                supports_toggle = provider_name.strip().lower() == "apinex" and options.get("toggle") is True
                thinking_input = request_data.get("thinking")
                thinking_type = (thinking_input.get("type")
                                 if isinstance(thinking_input, dict) else None)
                if supports_toggle:
                    effort_requests_off = str(requested or "").strip().lower() in {"none", "off", "disabled"}
                    disabled = (
                        thinking_type == "disabled"
                        or (thinking_type != "enabled" and request_data.get("alpha_reasoning") is False)
                        or (thinking_type != "enabled" and effort_requests_off)
                    )
                    if disabled:
                        payload["thinking"] = {"type": "disabled"}
                        payload.pop(parameter, None)
                        payload.pop("reasoning_effort", None)
                    else:
                        effort = str(requested or default_effort).strip().lower()
                        if effort not in allowed:
                            effort = str(default_effort).strip().lower()
                        if effort not in allowed:
                            effort = allowed[-1]
                        payload["thinking"] = {"type": "enabled"}
                        payload[parameter] = effort
                else:
                    # Regolo currently supports levels only, not an OFF switch.
                    if request_data.get("alpha_reasoning") is False:
                        requested = allowed[0]
                    effort = str(requested or default_effort).strip().lower()
                    if effort not in allowed:
                        effort = str(default_effort).strip().lower()
                    if effort not in allowed:
                        effort = allowed[-1]
                    payload[parameter] = effort

    return payload


def contains_image_input(messages: list[dict]) -> bool:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}:
                    return True
    return False


def _parse_data_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or not url.startswith("data:"):
        raise ProviderFailure("For this model, images must be attached as base64 data URLs", False)
    try:
        metadata, encoded = url.split(",", 1)
        if ";base64" not in metadata:
            raise ValueError("not base64")
        mime_type = metadata[5:].split(";", 1)[0].lower()
        if mime_type not in IMAGE_MIME_TYPES:
            raise ValueError("unsupported mime")
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_INLINE_IMAGE_BYTES:
            raise ValueError("size")
        return mime_type, base64.b64encode(raw).decode("ascii")
    except (ValueError, binascii.Error) as exc:
        raise ProviderFailure("The attached image is invalid or exceeds the 15 MB limit", False) from exc


def _google_contents(messages: list[dict]):
    contents: list[dict] = []
    system_instruction = None
    tool_names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_instruction = str(content)
            continue
        if role == "assistant" and message.get("tool_calls"):
            parts = []
            for call in message.get("tool_calls") or []:
                fn = call.get("function") or {}
                call_id = call.get("id")
                name = fn.get("name")
                if call_id and name:
                    tool_names[call_id] = name
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                parts.append({"functionCall": {"name": name or "tool", "args": args}})
            if parts:
                contents.append({"role": "model", "parts": parts})
            if isinstance(content, str) and content:
                contents.append({"role": "model", "parts": [{"text": content}]})
            continue
        if role == "tool":
            call_id = message.get("tool_call_id", "")
            name = tool_names.get(call_id, message.get("name", "tool"))
            try:
                response_value = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                response_value = {"result": str(content)}
            contents.append({"role": "user", "parts": [{"functionResponse": {"name": name, "response": response_value if isinstance(response_value, dict) else {"result": response_value}}}]})
            continue
        google_role = "model" if role == "assistant" else "user"
        if isinstance(content, str):
            contents.append({"role": google_role, "parts": [{"text": content}]})
        elif isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"text", "input_text"}:
                    parts.append({"text": part.get("text", "")})
                elif part.get("type") in {"image_url", "input_image"}:
                    image_url = part.get("image_url")
                    if isinstance(image_url, dict):
                        image_url = image_url.get("url")
                    if not image_url and part.get("type") == "input_image":
                        image_url = part.get("image_url") or part.get("image")
                    mime, encoded = _parse_data_url(image_url or "")
                    parts.append({"inlineData": {"mimeType": mime, "data": encoded}})
            if parts:
                contents.append({"role": google_role, "parts": parts})
    return contents, system_instruction


def _google_tools(tools):
    declarations = []
    for tool in tools or []:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = tool["function"]
            declarations.append({
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
    return [{"functionDeclarations": declarations}] if declarations else None


def _google_tool_config(tool_choice):
    if not tool_choice:
        return None
    mode = tool_choice
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") or {}
        mode = "ANY" if tool_choice.get("type") == "function" else "AUTO"
        if fn.get("name"):
            return {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [fn["name"]]}}
    normalized = str(mode).upper()
    if normalized == "NONE":
        return {"functionCallingConfig": {"mode": "NONE"}}
    if normalized in {"REQUIRED", "ANY"}:
        return {"functionCallingConfig": {"mode": "ANY"}}
    return {"functionCallingConfig": {"mode": "AUTO"}}


def _google_request(model: ModelConfig, route, request_data: dict, messages: list[dict], api_key: str):
    contents, system_instruction = _google_contents(messages)
    generation: dict[str, Any] = {}
    if "temperature" in request_data:
        generation["temperature"] = request_data["temperature"]
    max_tokens = request_data.get("max_tokens") or request_data.get("max_completion_tokens")
    if max_tokens:
        generation["maxOutputTokens"] = max_tokens
    generation_defaults = (model.request_defaults or {}).get("generationConfig", {})
    generation.update(generation_defaults)
    defaults = dict(model.request_defaults or {})
    if model.supports_reasoning:
        # Thinking levels are model-specific: Gemini 3.6 Flash supports
        # minimal/low/medium/high; Gemma 4 supports high (on) and minimal (off).
        route_cfg = route.reasoning_config or {}
        thinking_cfg = dict(route_cfg.get("thinkingConfig") or {})
        options = dict(model.reasoning_options or {})
        allowed_levels = options.get("effort")
        if not isinstance(allowed_levels, list) or not allowed_levels:
            allowed_levels = ["low", "medium", "high"]
        allowed_levels = [str(value).strip().lower() for value in allowed_levels]
        default_level = (defaults.get("thinking_level") or defaults.get("reasoning_effort") or
                         ("medium" if "medium" in allowed_levels else allowed_levels[-1]))
        requested_effort = (request_data.get("thinking_level") or request_data.get("reasoning_effort") or default_level)
        if request_data.get("alpha_reasoning") is False:
            requested_effort = "minimal" if "minimal" in allowed_levels else allowed_levels[0]
        effort = str(requested_effort).strip().lower()
        if effort not in allowed_levels:
            effort = str(default_level).strip().lower()
        if effort not in allowed_levels:
            effort = allowed_levels[-1]
        thinking_cfg["thinkingLevel"] = effort
        generation["thinkingConfig"] = thinking_cfg
    else:
        generation.pop("thinkingConfig", None)
    body: dict[str, Any] = {"contents": contents, "generationConfig": generation}
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    tools = _google_tools(request_data.get("tools"))
    if tools:
        body["tools"] = tools
        tool_config = _google_tool_config(request_data.get("tool_choice"))
        if tool_config:
            body["toolConfig"] = tool_config
    return body, api_key


def _google_response(data: dict, public_model_id: str) -> dict:
    candidate = (data.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p and not p.get("thought")]
    tool_calls = []
    for idx, part in enumerate(parts):
        fn = part.get("functionCall") if isinstance(part, dict) else None
        if fn:
            tool_calls.append({
                "id": f"call_{idx}_{int(time.time())}", "type": "function",
                "function": {"name": fn.get("name", "tool"), "arguments": json.dumps(fn.get("args", {}), ensure_ascii=False)},
            })
    message = {"role": "assistant", "content": "\n".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = data.get("usageMetadata") or {}
    finish = (candidate.get("finishReason") or "STOP").upper()
    return {
        "id": "alpha-google-" + str(int(time.time() * 1000)),
        "object": "chat.completion", "created": int(time.time()), "model": public_model_id,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else ("length" if finish == "MAX_TOKENS" else "stop")}],
        "usage": {"prompt_tokens": usage.get("promptTokenCount", 0), "completion_tokens": usage.get("candidatesTokenCount", 0), "total_tokens": usage.get("totalTokenCount", 0)},
    }


def _safe_json_response(response: httpx.Response):
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderFailure(retryable=True, allow_model_fallback=True) from exc


def call_route(route, provider: Provider, credential, model: ModelConfig, request_data: dict, messages: list[dict]):
    secret = decrypt_secret(credential.secret_encrypted)
    timeout = httpx.Timeout(120.0, connect=12.0)
    try:
        if provider.protocol == "google_genai":
            body, _ = _google_request(model, route, request_data, messages, secret)
            url = f"{provider.base_url.rstrip('/')}/models/{route.upstream_model_id}:generateContent"
            response = httpx.post(url, params={"key": secret}, json=body, timeout=timeout)
        else:
            payload = _openai_payload(model, route, request_data, messages, stream=False, provider_name=getattr(provider, "name", ""))
            url = f"{provider.base_url.rstrip('/')}/chat/completions"
            response = httpx.post(url, headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, json=payload, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderFailure(retryable=True, allow_model_fallback=True) from exc
    except httpx.TransportError as exc:
        raise ProviderFailure(retryable=True, allow_model_fallback=True) from exc
    if response.status_code in RETRYABLE_STATUS:
        raise ProviderFailure(retryable=True, status_code=response.status_code, allow_model_fallback=True)
    if response.status_code in KEY_RETRY_STATUS:
        raise ProviderFailure("The configured upstream credential was rejected", retryable=True, status_code=response.status_code)
    if response.status_code == 404:
        raise ProviderFailure("The selected model route is unavailable", retryable=True, status_code=404, allow_model_fallback=True)
    if response.status_code >= 400:
        raise ProviderFailure("The selected Alpha model rejected the request", retryable=False, status_code=response.status_code)
    data = _safe_json_response(response)
    if provider.protocol == "google_genai":
        return _google_response(data, model.public_id)
    data["model"] = model.public_id
    data.pop("provider", None)
    data.pop("system_fingerprint", None)
    return data


def _sse_payloads(response: httpx.Response) -> Iterator[str]:
    for line in response.iter_lines():
        if line.startswith("data:"):
            value = line[5:].strip()
            if value:
                yield value


def _chunk(public_model_id: str, completion_id: str, created: int, delta: dict | None = None, finish_reason=None, usage=None):
    result = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": public_model_id,
              "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}]}
    if usage is not None:
        result["usage"] = usage
    return "data: " + json.dumps(result, ensure_ascii=False) + "\n\n"


def stream_route(route, provider: Provider, credential, model: ModelConfig, request_data: dict, messages: list[dict], stats: dict):
    """Yield actual upstream SSE chunks; this is incremental, not buffered synthesis."""
    secret = decrypt_secret(credential.secret_encrypted)
    timeout = httpx.Timeout(300.0, connect=15.0, read=180.0)
    completion_id = "chatcmpl-alpha-" + str(int(time.time() * 1000))
    created = int(time.time())
    yielded = False
    try:
        with httpx.Client(timeout=timeout) as client:
            if provider.protocol == "google_genai":
                body, _ = _google_request(model, route, {**request_data, "alpha_reasoning": request_data.get("alpha_reasoning", True)}, messages, secret)
                url = f"{provider.base_url.rstrip('/')}/models/{route.upstream_model_id}:streamGenerateContent"
                context = client.stream("POST", url, params={"key": secret, "alt": "sse"}, json=body)
            else:
                payload = _openai_payload(model, route, request_data, messages, stream=True, provider_name=getattr(provider, "name", ""))
                url = f"{provider.base_url.rstrip('/')}/chat/completions"
                context = client.stream("POST", url, headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, json=payload)
            with context as response:
                if response.status_code in RETRYABLE_STATUS:
                    raise ProviderFailure(retryable=True, status_code=response.status_code, allow_model_fallback=True)
                if response.status_code in KEY_RETRY_STATUS:
                    raise ProviderFailure("The configured upstream credential was rejected", retryable=True, status_code=response.status_code)
                if response.status_code == 404:
                    raise ProviderFailure("The selected model route is unavailable", retryable=True, status_code=404, allow_model_fallback=True)
                if response.status_code >= 400:
                    raise ProviderFailure("The selected Alpha model rejected the request", retryable=False, status_code=response.status_code)
                if provider.protocol != "google_genai":
                    for raw in _sse_payloads(response):
                        if raw == "[DONE]":
                            yield "data: [DONE]\n\n"
                            yielded = True
                            return
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        event["model"] = model.public_id
                        event.pop("provider", None)
                        event.pop("system_fingerprint", None)
                        if event.get("usage"):
                            stats["usage"] = event["usage"]
                        for choice in event.get("choices") or []:
                            delta = choice.get("delta") or {}
                            stats["text"] += delta.get("content") or ""
                            stats["reasoning"] += delta.get("reasoning_content") or delta.get("reasoning") or ""
                            for tool in delta.get("tool_calls") or []:
                                stats["text"] += ((tool.get("function") or {}).get("arguments") or "")
                        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                        yielded = True
                    if yielded:
                        yield "data: [DONE]\n\n"
                    return

                role_sent = False
                for raw in _sse_payloads(response):
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    candidate = (event.get("candidates") or [{}])[0]
                    content = (candidate.get("content") or {})
                    parts = content.get("parts") or []
                    if not role_sent:
                        yield _chunk(model.public_id, completion_id, created, {"role": "assistant"})
                        role_sent = yielded = True
                    for part_index, part in enumerate(parts):
                        if part.get("thought") and isinstance(part.get("text"), str):
                            stats["reasoning"] += part["text"]
                            yield _chunk(model.public_id, completion_id, created, {"reasoning_content": part["text"]})
                            yielded = True
                        elif isinstance(part.get("text"), str):
                            stats["text"] += part["text"]
                            yield _chunk(model.public_id, completion_id, created, {"content": part["text"]})
                            yielded = True
                        elif isinstance(part.get("functionCall"), dict):
                            stats["saw_tool_call"] = True
                            fn = part["functionCall"]
                            args = json.dumps(fn.get("args", {}), ensure_ascii=False)
                            stats["text"] += args
                            tool_delta = {"tool_calls": [{"index": part_index, "id": f"call_{completion_id}_{part_index}", "type": "function", "function": {"name": fn.get("name", "tool"), "arguments": args}}]}
                            yield _chunk(model.public_id, completion_id, created, tool_delta)
                            yielded = True
                    usage = event.get("usageMetadata") or {}
                    if usage:
                        stats["usage"] = {"prompt_tokens": usage.get("promptTokenCount", 0), "completion_tokens": usage.get("candidatesTokenCount", 0), "total_tokens": usage.get("totalTokenCount", 0)}
                    finish = candidate.get("finishReason")
                    if finish:
                        stats["finish_reason"] = "tool_calls" if stats.get("saw_tool_call") else ("length" if finish == "MAX_TOKENS" else "stop")
                yield _chunk(model.public_id, completion_id, created, {}, stats.get("finish_reason", "stop"), stats.get("usage"))
                yield "data: [DONE]\n\n"
                yielded = True
    except ProviderFailure:
        raise
    except httpx.TimeoutException as exc:
        raise ProviderFailure(retryable=True, allow_model_fallback=True) from exc
    except httpx.TransportError as exc:
        raise ProviderFailure(retryable=True, allow_model_fallback=True) from exc
    except Exception as exc:
        raise ProviderFailure(retryable=not yielded) from exc


def _credential_sort_key(credential: UserModelCredential):
    """Prefer healthy keys; temporarily move recently failing keys behind them."""
    failed_at = credential.last_failure_at
    recently_failed = False
    if failed_at is not None:
        if failed_at.tzinfo is None:
            failed_at = failed_at.replace(tzinfo=timezone.utc)
        code = str(credential.last_failure_code or "")
        cooldown = 900 if code in {"401", "402", "403"} else 60
        recently_failed = (datetime.now(timezone.utc) - failed_at).total_seconds() < cooldown
    attempted = credential.last_attempt_at
    attempted_ts = 0.0
    if attempted is not None:
        if attempted.tzinfo is None:
            attempted = attempted.replace(tzinfo=timezone.utc)
        attempted_ts = attempted.timestamp()
    return (1 if recently_failed else 0, int(credential.priority or 0), attempted_ts, int(credential.id or 0))


def _user_model_route(db: Session, user_id: int, model: ModelConfig):
    """Resolve the provider and every active key owned by this user/model pair."""
    from types import SimpleNamespace
    provider = db.get(Provider, model.provider_id)
    credentials = db.scalars(select(UserModelCredential).where(
        UserModelCredential.user_id == user_id,
        UserModelCredential.model_id == model.id,
        UserModelCredential.active.is_(True),
    )).all()
    credentials = sorted(credentials, key=_credential_sort_key)
    if not provider or not provider.active or not credentials:
        raise ProviderFailure("This model is not configured for your account", False)
    route = SimpleNamespace(
        upstream_model_id=model.upstream_model_id,
        reasoning_config={},
    )
    return route, provider, credentials


def _mark_credential_attempt(db: Session, credential: UserModelCredential):
    credential.last_attempt_at = datetime.now(timezone.utc)
    db.add(credential)
    db.commit()


def _record_credential_result(db: Session, credential: UserModelCredential, *, success: bool, status_code: int | None = None):
    now = datetime.now(timezone.utc)
    if success:
        credential.last_used_at = now
        credential.failure_count = 0
        credential.last_failure_at = None
        credential.last_failure_code = ""
    else:
        credential.last_failure_at = now
        credential.failure_count = int(credential.failure_count or 0) + 1
        credential.last_failure_code = str(status_code or "UPSTREAM")[:24]
    db.add(credential)
    db.commit()


def _attempt_completion_for_route(db, credentials, route, provider, model, request_data, messages):
    """Try customer-owned keys in least-recently-attempted order for one model route."""
    from types import SimpleNamespace
    failures: list[ProviderFailure] = []
    for credential in credentials:
        _mark_credential_attempt(db, credential)
        stored = SimpleNamespace(secret_encrypted=credential.secret_encrypted)
        try:
            result = call_route(route, provider, stored, model, request_data, messages)
        except ProviderFailure as exc:
            _record_credential_result(db, credential, success=False, status_code=exc.status_code or "UPSTREAM")
            failures.append(exc)
            if not exc.retryable:
                raise
            continue
        _record_credential_result(db, credential, success=True)
        return result, failures
    return None, failures


def complete_for_user(db: Session, user_id: int, model: ModelConfig, request_data: dict, messages: list[dict]):
    """Rotate through this user's active keys, then use configured model fallbacks if overloaded."""
    from types import SimpleNamespace
    route, provider, credentials = _user_model_route(db, user_id, model)
    result, failures = _attempt_completion_for_route(db, credentials, route, provider, model, request_data, messages)
    if result is not None:
        return result

    # A key/auth failure rotates keys only. A capacity/availability failure may
    # advance to a model fallback, using the same user's assigned keyset.
    allow_fallback = any(exc.allow_model_fallback for exc in failures)
    fallback_ids = list(model.fallback_upstream_ids or []) if allow_fallback else []
    for fallback_id in fallback_ids:
        fallback_route = SimpleNamespace(upstream_model_id=fallback_id, reasoning_config={})
        fallback_result, fallback_failures = _attempt_completion_for_route(
            db, credentials, fallback_route, provider, model, request_data, messages
        )
        if fallback_result is not None:
            return fallback_result
        failures.extend(fallback_failures)
        if fallback_failures and not any(exc.retryable for exc in fallback_failures):
            break
    if failures:
        raise failures[-1]
    raise ProviderFailure()


def _empty_stream_stats(stats: dict):
    stats.clear()
    stats.update({"text": "", "reasoning": "", "usage": None, "finish_reason": None, "saw_tool_call": False})


def stream_for_user(db: Session, user_id: int, model: ModelConfig, request_data: dict, messages: list[dict], stats: dict):
    """Stream via a user's keyset; retry/fallback only before any response chunk is sent."""
    from types import SimpleNamespace
    route, provider, credentials = _user_model_route(db, user_id, model)
    fallback_ids = list(model.fallback_upstream_ids or [])
    routes = [route]
    routes.extend(SimpleNamespace(upstream_model_id=value, reasoning_config={}) for value in fallback_ids)
    last_failures: list[ProviderFailure] = []

    for route_index, active_route in enumerate(routes):
        if route_index > 0 and not any(exc.allow_model_fallback for exc in last_failures):
            break
        for credential in credentials:
            _mark_credential_attempt(db, credential)
            stored = SimpleNamespace(secret_encrypted=credential.secret_encrypted)
            _empty_stream_stats(stats)
            sent_anything = False
            try:
                for item in stream_route(active_route, provider, stored, model, request_data, messages, stats):
                    if item.strip() != "data: [DONE]":
                        sent_anything = True
                    yield item
            except ProviderFailure as exc:
                _record_credential_result(db, credential, success=False, status_code=exc.status_code or "UPSTREAM")
                last_failures.append(exc)
                # Once any chunk has reached the client, switching providers would
                # corrupt a stream or duplicate output, so terminate transparently.
                if sent_anything or not exc.retryable:
                    raise
                continue
            _record_credential_result(db, credential, success=True)
            return
    if last_failures:
        raise last_failures[-1]
    raise ProviderFailure()
