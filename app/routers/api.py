import json
import math
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..models import (
    APIKey, ModelConfig, Provider, UserModelCredential,
    Subscription, UserModelGrant, UsageEvent,
)
from ..security import verify_api_key
from ..services.quota import get_usage, reserve_user_tokens, settle_reservation, QuotaExceeded
from ..services.prompt_engine import compose_messages, PromptNotConfigured
from ..services.provider_client import complete_for_user, stream_for_user, contains_image_input, ProviderFailure

router = APIRouter(prefix="/v1")


def current_key(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer API key")
    raw = authorization[7:].strip()
    if not raw.startswith("alpha_"):
        raise HTTPException(401, "Invalid API key")
    prefix = raw[:16]
    key = db.scalar(select(APIKey).where(APIKey.prefix == prefix, APIKey.active.is_(True)))
    if not key or not verify_api_key(raw, key.key_hash):
        raise HTTPException(401, "Invalid or disabled API key")
    if not key.user.active:
        raise HTTPException(403, "User account is disabled")
    now = datetime.now(timezone.utc)
    subscription = db.scalar(select(Subscription).where(
        Subscription.user_id == key.user_id,
        Subscription.status == "active",
        Subscription.starts_at <= now,
        Subscription.ends_at > now,
    ).order_by(Subscription.ends_at.desc()))
    if not subscription:
        raise HTTPException(403, "No active subscription")
    key.last_used_at = now
    db.commit()
    return key, subscription


def model_is_provisioned(db: Session, user_id: int, model: ModelConfig) -> bool:
    if not model.active or not (model.system_prompt or "").strip():
        return False
    grant = db.scalar(select(UserModelGrant).where(
        UserModelGrant.user_id == user_id,
        UserModelGrant.model_id == model.id,
        UserModelGrant.active.is_(True),
    ))
    if not grant:
        return False
    provider = db.get(Provider, model.provider_id)
    if not provider or not provider.active:
        return False
    credential = db.scalar(select(UserModelCredential.id).where(
        UserModelCredential.user_id == user_id,
        UserModelCredential.model_id == model.id,
        UserModelCredential.active.is_(True),
    ))
    return credential is not None


@router.get("/models")
def list_models(auth=Depends(current_key), db: Session = Depends(get_db)):
    key, _ = auth
    models = db.scalars(select(ModelConfig).where(ModelConfig.active.is_(True)).order_by(ModelConfig.public_name)).all()
    visible = [m for m in models if model_is_provisioned(db, key.user_id, m)]
    data = []
    for model in visible:
        defaults = model.request_defaults or {}
        options = model.reasoning_options or {}
        default_effort = (
            defaults.get(model.reasoning_parameter)
            or defaults.get("reasoning_effort")
            or defaults.get("thinking_level")
        )
        data.append({
            "id": model.public_id,
            "object": "model",
            "created": int(model.created_at.timestamp()) if getattr(model, "created_at", None) else 0,
            "owned_by": "alpha",
            "context_window": int(defaults.get("alpha_context_window") or 0),
            "max_output_tokens": int(defaults.get("alpha_max_output_tokens") or 0),
            "capabilities": {
                "tools": bool(model.supports_tools),
                "vision": bool(model.supports_vision),
                "reasoning": {
                    "supported": bool(model.supports_reasoning),
                    "effort": list(options.get("effort") or []),
                    "toggle": bool(options.get("toggle")),
                    "default": default_effort,
                },
            },
        })
    return {"object": "list", "data": data}


@router.get("/quota")
def quota(auth=Depends(current_key), db: Session = Depends(get_db)):
    key, subscription = auth
    usage = get_usage(db, key.user_id)
    return {
        "scope": "user_account",
        "daily_limit": subscription.plan.daily_token_limit,
        "used_tokens": usage.total_tokens,
        "reserved_tokens": usage.reserved_tokens,
        "remaining_tokens": max(0, subscription.plan.daily_token_limit - usage.total_tokens - usage.reserved_tokens),
        "api_key_note": "All API keys and all entitled models owned by this user share this quota.",
        "resets_at": "00:00 UTC",
    }


def _estimate_tokens(value) -> int:
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        serialized = str(value)
    return max(1, math.ceil(len(serialized.encode("utf-8")) / 2.5))


def _stream_error(message: str):
    return "data: " + json.dumps({"error": {"message": message, "type": "server_error"}}, ensure_ascii=False) + "\n\n"


def _stream_chat_response(user_id: int, api_key_id: int, model: ModelConfig, body: dict, messages: list[dict], reservation: int, prompt_estimate: int):
    """Owns its DB session for the response lifetime and accounts partial/cancelled streams."""
    stream_db = SessionLocal()
    stats = {"text": "", "reasoning": "", "usage": {}, "interrupted": False}
    final_status = "success"
    try:
        for event in stream_for_user(stream_db, user_id, model, body, messages, stats):
            if stats.get("interrupted"):
                final_status = "stream_interrupted"
            yield event
    except ProviderFailure as exc:
        final_status = "upstream_unavailable"
        yield _stream_error(str(exc) if not exc.retryable else "The selected Alpha model is temporarily unavailable")
        yield "data: [DONE]\n\n"
    except GeneratorExit:
        final_status = "stream_cancelled"
        raise
    except Exception:
        final_status = "stream_interrupted"
        yield _stream_error("Alpha could not complete the stream. Please retry later.")
        yield "data: [DONE]\n\n"
    finally:
        try:
            if stats.get("interrupted") and final_status == "success":
                final_status = "stream_interrupted"
            usage = stats.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0) or 0)
            output_tokens = int(usage.get("completion_tokens", 0) or 0)
            actual_tokens = int(usage.get("total_tokens", 0) or 0)
            if actual_tokens <= 0:
                input_tokens = prompt_estimate
                output_tokens = _estimate_tokens(stats.get("text", "") + stats.get("reasoning", ""))
                actual_tokens = input_tokens + output_tokens
            settle_reservation(stream_db, user_id, reservation, actual_tokens)
            stream_db.add(UsageEvent(
                user_id=user_id, api_key_id=api_key_id, model_public_id=model.public_id,
                provider_name="account-model-credential", input_tokens=input_tokens,
                output_tokens=output_tokens, total_tokens=actual_tokens, status=final_status,
            ))
            stream_db.commit()
        except Exception:
            stream_db.rollback()
        finally:
            stream_db.close()


@router.post("/chat/completions")
def chat_completions(request: Request, body: dict, auth=Depends(current_key), db: Session = Depends(get_db)):
    key, subscription = auth
    model_id = body.get("model")
    if not isinstance(model_id, str):
        raise HTTPException(400, "A public Alpha model ID is required")
    model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == model_id, ModelConfig.active.is_(True)))
    if not model or not model_is_provisioned(db, key.user_id, model):
        raise HTTPException(404, "The requested Alpha model is not available for this account")
    incoming_messages = body.get("messages")
    if not isinstance(incoming_messages, list) or not incoming_messages:
        raise HTTPException(400, "messages must be a non-empty array")
    if contains_image_input(incoming_messages) and not bool(getattr(model, "supports_vision", False)):
        raise HTTPException(400, "This Alpha model accepts text only. Choose an image-capable model.")
    if body.get("tools") and not model.supports_tools:
        raise HTTPException(400, "Tool calling is not available for this Alpha model.")
    if body.get("stream") is True and not model.supports_streaming:
        raise HTTPException(400, "Streaming is not available for this Alpha model.")
    try:
        messages = compose_messages(model, incoming_messages)
    except PromptNotConfigured:
        raise HTTPException(503, "Alpha is not ready: the administrator has not configured this model’s System Prompt")

    model_defaults = model.request_defaults or {}
    try:
        model_output_ceiling = int(model_defaults.get("alpha_max_output_tokens") or 32768)
        if model_output_ceiling < 1 or model_output_ceiling > 1_000_000:
            raise ValueError("invalid model output ceiling")
    except (TypeError, ValueError):
        raise HTTPException(503, "The selected model has an invalid output-token configuration")
    requested_output = body.get("max_tokens") or body.get("max_completion_tokens") or min(8192, model_output_ceiling)
    try:
        output_cap = max(1, min(int(requested_output), model_output_ceiling))
    except (TypeError, ValueError):
        raise HTTPException(400, "max_tokens must be a positive integer")
    body["max_tokens"] = output_cap
    body.pop("max_completion_tokens", None)
    # Reserve for estimated prompt plus the maximum configured output before contacting providers.
    reservation = _estimate_tokens(messages) + output_cap
    try:
        reserve_user_tokens(db, key.user_id, subscription.plan.daily_token_limit, reservation)
    except QuotaExceeded:
        raise HTTPException(429, "Daily user quota exceeded. All your Alpha API keys share this daily limit.")

    if body.get("stream") is True:
        prompt_estimate = _estimate_tokens(messages)
        return StreamingResponse(
            _stream_chat_response(key.user_id, key.id, model, body, messages, reservation, prompt_estimate),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    try:
        result = complete_for_user(db, key.user_id, model, body, messages)
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        actual_tokens = int(usage.get("total_tokens", 0) or (input_tokens + output_tokens))
        if actual_tokens <= 0:
            input_tokens = _estimate_tokens(messages)
            output_tokens = _estimate_tokens((result.get("choices") or [{}])[0].get("message", {}).get("content", ""))
            actual_tokens = input_tokens + output_tokens
        # Fail closed against under-reservation; actual accounting still reflects provider-reported usage.
        settle_reservation(db, key.user_id, reservation, actual_tokens)
        db.add(UsageEvent(
            user_id=key.user_id, api_key_id=key.id, model_public_id=model.public_id,
            provider_name="account-model-credential", input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=actual_tokens, status="success",
        ))
        db.commit()
    except ProviderFailure as exc:
        settle_reservation(db, key.user_id, reservation, 0)
        db.add(UsageEvent(user_id=key.user_id, api_key_id=key.id, model_public_id=model.public_id, provider_name="account-model-credential", status="upstream_unavailable"))
        db.commit()
        raise HTTPException(503 if exc.retryable else 502, str(exc))
    except Exception:
        db.rollback()
        try:
            settle_reservation(db, key.user_id, reservation, 0)
        except Exception:
            db.rollback()
        raise HTTPException(502, "Alpha could not complete the request. Please retry later.")

    result["model"] = model.public_id
    return result
