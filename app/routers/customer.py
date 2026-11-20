from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from decimal import Decimal
import json
import secrets
import re
import logging
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import Admin, APIKey, ModelConfig, Plan, PurchaseOrder, Subscription, User, UserDailyUsage, UserModelGrant, UserModelCredential, Provider, PaymentMethodSetting, PaymentSubmission, UsageEvent
from ..security import hash_password, verify_password, create_api_key, decrypt_secret, encrypt_secret
from ..services.quota import get_usage
from ..config import settings
from ..services.manual_payments import payment_day_window_utc, submissions_used_today, reserve_daily_submission_slot

router = APIRouter()
logger = logging.getLogger("alphax.customer")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def customer_id(request: Request):
    return request.session.get("user_id")


def current_user(request: Request, db: Session):
    uid = customer_id(request)
    user = db.get(User, uid) if uid else None
    if not user or not user.active:
        request.session.pop("user_id", None)
        raise HTTPException(303, headers={"Location": "/login"})
    return user


def csrf_token(request: Request) -> str:
    token = request.session.get("customer_csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["customer_csrf"] = token
    return token


def check_csrf(request: Request, token: str):
    import hmac
    expected = request.session.get("customer_csrf", "")
    if not expected or not hmac.compare_digest(expected, token):
        raise HTTPException(403, "Invalid CSRF token")


def render(request: Request, name: str, **context):
    return templates.TemplateResponse(request, name, {"csrf": csrf_token(request), **context})


def _is_username_unique_violation(exc: IntegrityError) -> bool:
    """Return True only when the violated constraint is the customer username."""
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if constraint_name:
        return constraint_name in {
            "ix_users_username", "uq_users_username", "users_username_key"
        }
    message = str(original or exc).lower()
    return (
        "unique constraint failed: users.username" in message
        or 'duplicate key value violates unique constraint "ix_users_username"' in message
        or 'duplicate key value violates unique constraint "users_username_key"' in message
        or 'duplicate key value violates unique constraint "uq_users_username"' in message
    )


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "customer_auth.html", mode="register", error=None)


@router.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,29}", username):
        return render(request, "customer_auth.html", mode="register", error="Username must be 3–30 characters and use only letters, numbers, dots, hyphens, or underscores.")
    if len(password) < 10:
        return render(request, "customer_auth.html", mode="register", error="Password must be at least 10 characters long.")
    reserved_admin = db.scalar(select(Admin.id).where(func.lower(Admin.username) == username))
    if reserved_admin:
        return render(request, "customer_auth.html", mode="register", error="This username is reserved. Please choose another one.")
    if db.scalar(select(User.id).where(func.lower(User.username) == username)):
        return render(request, "customer_auth.html", mode="register", error="This username is already taken. Please choose another one.")

    # The legacy email column remains populated internally for old schema compatibility;
    # it is not collected, displayed, or used for customer authentication.
    internal_email = f"acct-{secrets.token_hex(16)}@accounts.alphax.invalid"
    user = User(email=internal_email, username=username, display_name=username,
                password_hash=hash_password(password), active=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_username_unique_violation(exc):
            return render(request, "customer_auth.html", mode="register", error="This username is already taken. Please choose another one.")
        constraint_name = getattr(getattr(getattr(exc, "orig", None), "diag", None), "constraint_name", None)
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        # Do not log SQL parameters or password hashes. The detailed cause stays in
        # the server's DB diagnostics, while users receive an honest non-duplicate error.
        logger.error("Customer registration failed on a non-username database constraint (constraint=%r, sqlstate=%r)", constraint_name, sqlstate)
        return render(request, "customer_auth.html", mode="register", error="We couldn't create your account because of a database error. Please try again later.")
    db.refresh(user)
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/account", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "customer_auth.html", mode="login", error=None)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    """One sign-in form: admins and customers both use usernames."""
    check_csrf(request, csrf)
    username = username.strip().lower()

    admin = db.scalar(select(Admin).where(func.lower(Admin.username) == username))
    if admin:
        if admin.active and verify_password(password, admin.password_hash):
            request.session.clear()
            request.session["admin_id"] = admin.id
            request.session["csrf"] = secrets.token_urlsafe(24)
            return RedirectResponse("/admin", status_code=303)
        return render(request, "customer_auth.html", mode="login", error="Incorrect username or password.")

    user = db.scalar(select(User).where(func.lower(User.username) == username))
    if not user:
        return render(request, "customer_auth.html", mode="login", error="Account not found. Please create a new account.")
    if not user.active:
        return render(request, "customer_auth.html", mode="login", error="This account is disabled. Contact the administrator.")
    if not user.password_hash or not verify_password(password, user.password_hash):
        return render(request, "customer_auth.html", mode="login", error="Incorrect username or password.")
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/account", status_code=303)


@router.post("/account/logout")
def logout(request: Request, csrf: str = Form(...)):
    check_csrf(request, csrf)
    request.session.pop("user_id", None)
    return RedirectResponse("/login", status_code=303)


@router.get("/account", response_class=HTMLResponse)
def account(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    plans = db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.daily_token_limit)).all()
    payment_methods = db.scalars(select(PaymentMethodSetting).where(PaymentMethodSetting.active.is_(True), PaymentMethodSetting.receiver_code != "").order_by(PaymentMethodSetting.id)).all()
    models = db.scalars(select(ModelConfig).where(ModelConfig.active.is_(True)).order_by(ModelConfig.public_name)).all()
    default_model_images = {
        "y5z-coder-pro": "/static/images/models/y5z-coder-pro-user.webp",
        "alphax-pro": "/static/images/models/alphax-group-user.webp",
        "alphax-max": "/static/images/models/alphax-group-user.webp",
    }
    for model in models:
        model.public_skills = model.public_skills or []
        model.public_highlights = model.public_highlights or []
        model.public_image = model.public_image or default_model_images.get(model.public_id, "/static/images/models/y5z-coder-pro-user.webp")
    orders = db.scalars(select(PurchaseOrder).options(joinedload(PurchaseOrder.plan)).where(PurchaseOrder.user_id == user.id).order_by(PurchaseOrder.id.desc())).all()
    subscriptions = db.scalars(select(Subscription).options(joinedload(Subscription.plan)).where(Subscription.user_id == user.id).order_by(Subscription.id.desc())).all()
    keys = db.scalars(select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.id.desc())).all()
    usage = get_usage(db, user.id)
    now_utc = datetime.now(timezone.utc)
    active_sub = next((
        s for s in subscriptions
        if s.status == "active" and s.ends_at and
        (s.ends_at.replace(tzinfo=timezone.utc) if s.ends_at.tzinfo is None else s.ends_at) > now_utc
    ), None)
    remaining_tokens = max(0, active_sub.plan.daily_token_limit - usage.total_tokens - usage.reserved_tokens) if active_sub else 0
    grants = db.scalars(select(UserModelGrant).options(joinedload(UserModelGrant.model)).where(UserModelGrant.user_id == user.id, UserModelGrant.active.is_(True))).all()
    revealable_keys = [k.id for k in keys if k.secret_delivery_encrypted]
    active_keys = [k for k in keys if k.active]

    # Customer analytics are built from real gateway UsageEvent rows, not preview numbers.
    now_utc = datetime.now(timezone.utc)
    seven_day_start = now_utc - timedelta(days=7)
    thirty_day_start = now_utc - timedelta(days=30)
    recent_events_7d = db.scalars(select(UsageEvent).where(
        UsageEvent.user_id == user.id,
        UsageEvent.created_at >= seven_day_start,
    ).order_by(UsageEvent.created_at.asc())).all()
    recent_events_30d = db.scalars(select(UsageEvent).where(
        UsageEvent.user_id == user.id,
        UsageEvent.created_at >= thirty_day_start,
    )).all()

    daily_totals = {}
    for event in recent_events_7d:
        created = event.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        event_day = created.astimezone(timezone.utc).date()
        daily_totals[event_day] = daily_totals.get(event_day, 0) + int(event.total_tokens or 0)
    today_utc = now_utc.date()
    chart_values = [
        {"date": today_utc - timedelta(days=offset), "tokens": daily_totals.get(today_utc - timedelta(days=offset), 0)}
        for offset in range(6, -1, -1)
    ]
    max_daily = max((item["tokens"] for item in chart_values), default=0)
    daily_usage_chart = [
        {"label": item["date"].strftime("%a"), "tokens": item["tokens"],
         "height": max(4, round(item["tokens"] / max_daily * 100)) if max_daily else 4}
        for item in chart_values
    ]

    model_names = {model.public_id: model.public_name for model in models}
    model_totals = {}
    for event in recent_events_30d:
        public_id = event.model_public_id or "unknown"
        model_totals[public_id] = model_totals.get(public_id, 0) + int(event.total_tokens or 0)
    total_model_tokens = sum(model_totals.values())
    model_usage_stats = [
        {"name": model_names.get(public_id, public_id.replace("-", " ").title()),
         "tokens": tokens,
         "percent": round(tokens / total_model_tokens * 100) if total_model_tokens else 0}
        for public_id, tokens in sorted(model_totals.items(), key=lambda item: item[1], reverse=True)
        if tokens > 0
    ]
    daily_limit = active_sub.plan.daily_token_limit if active_sub else 0
    quota_percent = min(100, round((usage.total_tokens + usage.reserved_tokens) / daily_limit * 100)) if daily_limit else 0
    def plan_has_price(plan):
        try:
            return Decimal(str(plan.price_amount or "0")) > 0
        except Exception:
            return False

    pending_order = db.scalar(select(PurchaseOrder).where(
        PurchaseOrder.user_id == user.id,
        PurchaseOrder.status.in_(["awaiting_payment", "payment_review", "paid_pending_setup", "provisioning"]),
    ).order_by(PurchaseOrder.id.desc()))
    can_purchase = bool(payment_methods and models and any(plan_has_price(plan) for plan in plans) and not pending_order)
    can_generate_key = False
    if active_sub:
        for grant in grants:
            model = grant.model
            provider = db.get(Provider, model.provider_id) if model else None
            credential = db.scalar(select(UserModelCredential.id).where(
                UserModelCredential.user_id == user.id,
                UserModelCredential.model_id == grant.model_id,
                UserModelCredential.active.is_(True),
            ))
            if model and model.active and (model.system_prompt or "").strip() and provider and provider.active and credential:
                can_generate_key = True
                break
    public_root = (settings.public_base_url or str(request.base_url)).rstrip("/")
    api_base_url = public_root + "/v1"
    return render(
        request, "account.html", user=user, plans=plans, models=models, orders=orders,
        subscriptions=subscriptions, keys=keys, active_keys=active_keys, usage=usage,
        active_sub=active_sub, remaining_tokens=remaining_tokens, grants=grants,
        revealable_keys=revealable_keys, payment_methods=payment_methods,
        daily_usage_chart=daily_usage_chart, model_usage_stats=model_usage_stats,
        request_count_7d=len(recent_events_7d), daily_limit=daily_limit,
        quota_percent=quota_percent, can_purchase=can_purchase, can_generate_key=can_generate_key, pending_order=pending_order, api_base_url=api_base_url,
    )


@router.post("/account/purchase")
def purchase(
    request: Request, plan_id: int = Form(...), model_ids: list[str] = Form(...),
    payment_method: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    user = current_user(request, db)
    pending = db.scalar(select(PurchaseOrder).where(
        PurchaseOrder.user_id == user.id,
        PurchaseOrder.status.in_(["awaiting_payment", "payment_review", "paid_pending_setup", "provisioning"]),
    ).order_by(PurchaseOrder.id.desc()))
    if pending:
        return RedirectResponse(f"/account/orders/{pending.id}/pay", status_code=303)
    plan = db.get(Plan, plan_id)
    if not plan or not plan.active:
        raise HTTPException(400, "The selected plan is unavailable")
    if not model_ids:
        raise HTTPException(400, "Select at least one model")
    method = db.scalar(select(PaymentMethodSetting).where(
        PaymentMethodSetting.method == payment_method,
        PaymentMethodSetting.active.is_(True),
    ))
    if not method or not method.receiver_code.strip():
        raise HTTPException(503, "The selected payment method is currently unavailable")
    unique_ids = list(dict.fromkeys(model_ids))
    models = db.scalars(select(ModelConfig).where(ModelConfig.public_id.in_(unique_ids), ModelConfig.active.is_(True))).all()
    if len(models) != len(unique_ids):
        raise HTTPException(400, "One of the requested models is unavailable")
    try:
        amount = Decimal(plan.price_amount)
    except Exception:
        raise HTTPException(400, "The plan price is invalid")
    if amount <= 0:
        raise HTTPException(400, "An administrator must set the plan price before it can be sold")
    order = PurchaseOrder(
        user_id=user.id, plan_id=plan.id, requested_model_ids=unique_ids,
        status="awaiting_payment", merchant_trade_no="ALPHA" + secrets.token_hex(12).upper(),
        amount=str(amount), currency=plan.currency, payment_method=method.method,
    )
    db.add(order); db.commit(); db.refresh(order)
    return RedirectResponse(f"/account/orders/{order.id}/pay", status_code=303)


@router.get("/account/orders/{order_id}/pay", response_class=HTMLResponse)
def payment_instructions(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    order = db.scalar(select(PurchaseOrder).options(joinedload(PurchaseOrder.plan)).where(
        PurchaseOrder.id == order_id, PurchaseOrder.user_id == user.id,
    ))
    if not order:
        raise HTTPException(404, "Order not found")
    method = db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == order.payment_method))
    if not method:
        raise HTTPException(404, "Payment instructions not found")
    submissions = db.scalars(select(PaymentSubmission).where(
        PaymentSubmission.order_id == order.id
    ).order_by(PaymentSubmission.id.desc())).all()
    try:
        display_tz = ZoneInfo(settings.payment_review_timezone)
    except ZoneInfoNotFoundError:
        display_tz = ZoneInfo("Asia/Damascus")
    for item in submissions:
        paid = item.paid_at.replace(tzinfo=timezone.utc) if item.paid_at.tzinfo is None else item.paid_at
        sent = item.submitted_at.replace(tzinfo=timezone.utc) if item.submitted_at.tzinfo is None else item.submitted_at
        item.paid_at_display = paid.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        item.submitted_at_display = sent.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    start_utc, end_utc, day_key = payment_day_window_utc()
    used_today = submissions_used_today(db, user.id, start_utc, end_utc)
    return render(
        request, "payment_instructions.html", user=user, order=order, method=method,
        submissions=submissions, used_today=used_today,
        remaining_today=max(0, 2 - used_today), error=request.query_params.get("error"),
        review_timezone=settings.payment_review_timezone,
    )


@router.post("/account/orders/{order_id}/submit-payment")
def submit_manual_payment(
    request: Request, order_id: int, reference_code: str = Form(...),
    paid_at_local: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    user = current_user(request, db)
    order = db.scalar(select(PurchaseOrder).where(
        PurchaseOrder.id == order_id, PurchaseOrder.user_id == user.id,
    ))
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status not in {"awaiting_payment", "payment_rejected"}:
        raise HTTPException(409, "A new proof cannot be submitted for this order right now")
    code = reference_code.strip()
    if len(code) < 4 or len(code) > 160:
        raise HTTPException(400, "Enter a valid transaction reference")
    start_utc, end_utc, day_key = payment_day_window_utc()
    used_today = submissions_used_today(db, user.id, start_utc, end_utc)
    if used_today >= 2:
        return RedirectResponse(f"/account/orders/{order_id}/pay?error=daily_limit", status_code=303)
    method = db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == order.payment_method))
    if not method:
        raise HTTPException(400, "Unknown payment method")
    normalized = " ".join(code.casefold().split())
    duplicate = db.scalar(select(PaymentSubmission.id).where(
        PaymentSubmission.method == order.payment_method,
        PaymentSubmission.reference_code_normalized == normalized,
    ))
    if duplicate:
        return RedirectResponse(f"/account/orders/{order_id}/pay?error=duplicate", status_code=303)
    try:
        try:
            payment_tz = ZoneInfo(settings.payment_review_timezone)
        except ZoneInfoNotFoundError:
            payment_tz = ZoneInfo("Asia/Damascus")
        parsed = datetime.fromisoformat(paid_at_local)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=payment_tz)
        paid_at_utc = parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return RedirectResponse(f"/account/orders/{order_id}/pay?error=invalid_date", status_code=303)
    if paid_at_utc > datetime.now(timezone.utc) + timedelta(minutes=15):
        return RedirectResponse(f"/account/orders/{order_id}/pay?error=future_date", status_code=303)
    if not reserve_daily_submission_slot(db, user.id, day_key, limit=2):
        db.rollback()
        return RedirectResponse(f"/account/orders/{order_id}/pay?error=daily_limit", status_code=303)
    submission = PaymentSubmission(
        order_id=order.id, user_id=user.id, method=order.payment_method,
        reference_code=code, reference_code_normalized=normalized,
        paid_at=paid_at_utc, status="pending",
    )
    db.add(submission)
    order.status = "payment_review"
    try:
        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse(f"/account/orders/{order_id}/pay?error=duplicate", status_code=303)
    return RedirectResponse(f"/account/orders/{order_id}/pay?submitted=1", status_code=303)


@router.get("/account/keys/{key_id}/reveal", response_class=HTMLResponse)
def reveal_key(request: Request, key_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    key = db.scalar(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id))
    if not key or not key.secret_delivery_encrypted:
        raise HTTPException(404, "No new key is available to reveal")
    raw = decrypt_secret(key.secret_delivery_encrypted)
    key.secret_delivery_encrypted = None
    db.commit()
    public_root = (settings.public_base_url or str(request.base_url)).rstrip("/")
    return render(request, "key_reveal.html", raw_key=raw, api_base_url=public_root + "/v1")


@router.post("/account/api-key/generate")
def generate_customer_api_key(request: Request, csrf: str = Form(...), key_name: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    now = datetime.now(timezone.utc)
    subscription = db.scalar(select(Subscription).where(
        Subscription.user_id == user.id,
        Subscription.status == "active",
        Subscription.starts_at <= now,
        Subscription.ends_at > now,
    ).order_by(Subscription.ends_at.desc()))
    if not subscription:
        raise HTTPException(403, "An active subscription is required before generating an API key")

    grants = db.scalars(select(UserModelGrant).where(
        UserModelGrant.user_id == user.id, UserModelGrant.active.is_(True),
    )).all()
    ready = []
    for grant in grants:
        model = db.get(ModelConfig, grant.model_id)
        provider = db.get(Provider, model.provider_id) if model else None
        credential = db.scalar(select(UserModelCredential).where(
            UserModelCredential.user_id == user.id,
            UserModelCredential.model_id == grant.model_id,
            UserModelCredential.active.is_(True),
        ))
        if model and model.active and (model.system_prompt or "").strip() and provider and provider.active and credential:
            ready.append(model.id)
    if not ready:
        raise HTTPException(409, "Your account has no fully prepared model yet. Contact support.")

    # Every generated gateway key is independent. Creating a new one never revokes older keys.
    raw, prefix, key_hash = create_api_key()
    cleaned_name = (key_name or "").strip()[:100]
    if not cleaned_name:
        existing_count = db.scalar(select(func.count(APIKey.id)).where(APIKey.user_id == user.id)) or 0
        cleaned_name = f"AlphaX Key {existing_count + 1}"
    try:
        delivery = encrypt_secret(raw)
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(503, "API key generation is temporarily unavailable") from exc
    key = APIKey(user_id=user.id, name=cleaned_name, prefix=prefix,
                 key_hash=key_hash, active=True, secret_delivery_encrypted=delivery)
    db.add(key)
    db.commit()
    return RedirectResponse("/account?api_key=generated", status_code=303)


@router.post("/account/keys/{key_id}/revoke")
def revoke_customer_api_key(request: Request, key_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    key = db.scalar(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id))
    if not key:
        raise HTTPException(404, "API key not found")
    if key.active:
        key.active = False
        key.secret_delivery_encrypted = None
        db.commit()
    return RedirectResponse("/account?api_key=revoked", status_code=303)


@router.get("/account/opencode-config")
def opencode_config(request: Request, db: Session = Depends(get_db)):
    """Download an OpenCode v2 config that exposes only AlphaX's public model aliases."""
    user = current_user(request, db)
    active_sub = db.scalar(select(Subscription).where(
        Subscription.user_id == user.id,
        Subscription.status == "active",
        Subscription.ends_at > datetime.now(timezone.utc),
    ).order_by(Subscription.ends_at.desc()))
    if not active_sub:
        raise HTTPException(403, "No active subscription")
    grants = db.scalars(select(UserModelGrant).options(joinedload(UserModelGrant.model)).where(
        UserModelGrant.user_id == user.id, UserModelGrant.active.is_(True)
    )).all()
    model_entries: dict[str, dict] = {}
    for grant in grants:
        model = grant.model
        provider = db.get(Provider, model.provider_id)
        active_credentials = db.scalars(select(UserModelCredential.id).where(
            UserModelCredential.user_id == user.id,
            UserModelCredential.model_id == model.id,
            UserModelCredential.active.is_(True),
        ).limit(1)).first()
        if not model.active or not (model.system_prompt or "").strip() or not provider or not provider.active or not active_credentials:
            continue

        capabilities = {
            "tools": bool(model.supports_tools),
            "input": ["text", "image"] if model.supports_vision else ["text"],
            "output": ["text"],
        }
        reasoning_options = dict(model.reasoning_options or {})
        if model.supports_reasoning:
            reasoning_capability = {"supported": True}
            if reasoning_options.get("toggle") is True:
                # OpenCode generates a dedicated `none` variant for this toggle.
                reasoning_capability["toggle"] = True
            effort = reasoning_options.get("effort")
            if model.reasoning_mode == "levels" and isinstance(effort, list):
                allowed = [str(item) for item in effort if str(item) in {"minimal", "low", "medium", "high"}]
                if allowed:
                    reasoning_capability["effort"] = allowed
            capabilities["reasoning"] = reasoning_capability

        variants = []
        for variant in model.reasoning_variants or []:
            if not isinstance(variant, dict) or not variant.get("id"):
                continue
            clean_variant = {"id": str(variant["id"])[:40]}
            body = variant.get("body")
            if isinstance(body, dict):
                safe_body = {}
                allowed_efforts = set(str(item) for item in (reasoning_options.get("effort") or ["low", "medium", "high"]))
                if body.get("reasoning_effort") in allowed_efforts and model.reasoning_mode == "levels":
                    safe_body["reasoning_effort"] = body["reasoning_effort"]
                if body.get("thinking_level") in allowed_efforts and model.reasoning_mode == "levels":
                    safe_body["thinking_level"] = body["thinking_level"]
                if safe_body:
                    clean_variant["body"] = safe_body
            settings_value = variant.get("settings")
            if isinstance(settings_value, dict):
                safe_settings = {k: v for k, v in settings_value.items() if k == "reasoningEffort" and v in {"low", "medium", "high"}}
                if safe_settings:
                    clean_variant["settings"] = safe_settings
            if len(clean_variant) > 1:
                variants.append(clean_variant)

        entry = {
            "name": model.public_name,
            # The gateway accepts only its public alias; never export the upstream ID.
            "modelID": model.public_id,
            "limit": {"context": 131072, "output": 32768},
            "capabilities": capabilities,
        }
        if variants:
            entry["variants"] = variants
        model_entries[model.public_id] = entry

    active_key = db.scalar(select(APIKey).where(APIKey.user_id == user.id, APIKey.active.is_(True)).order_by(APIKey.id.desc()))
    if not active_key:
        raise HTTPException(409, "Generate an AlphaX API key in the account page first")
    if not model_entries:
        raise HTTPException(409, "No model has been fully configured for your account yet")
    first_model = next(iter(model_entries))
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"alphax/{first_model}",
        "providers": {
            "alphax": {
                "name": "AlphaX",
                "env": ["ALPHAX_API_KEY"],
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": (settings.public_base_url or str(request.base_url)).rstrip("/") + "/v1",
                },
                "models": model_entries,
            }
        },
    }
    return Response(content=json.dumps(cfg, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=alphax-opencode.json"})
