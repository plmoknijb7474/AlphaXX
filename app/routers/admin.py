from pathlib import Path
import json
import re
import secrets
import httpx
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import Admin, APIKey, ModelConfig, Plan, Provider, Subscription, User, UserDailyUsage, UserModelGrant, UserModelCredential, PurchaseOrder, PaymentMethodSetting, PaymentSubmission
from ..security import hash_password, verify_password, encrypt_secret, decrypt_secret
from ..config import settings

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def admin_required(request: Request, db: Session) -> Admin:
    admin_id = request.session.get("admin_id")
    if not admin_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    admin = db.get(Admin, admin_id)
    if not admin or not admin.active:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return admin


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        import secrets
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, token: str):
    import hmac
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def render(request: Request, name: str, **context):
    return templates.TemplateResponse(request, name, {"csrf": csrf_token(request), **context})


def append_customer_model_keys(db: Session, user_id: int, model_id: int, raw_lines: str) -> int:
    """Append distinct encrypted keys; never replace the user's existing keyset."""
    values = [line.strip() for line in (raw_lines or "").splitlines() if line.strip()]
    if not values:
        raise HTTPException(400, "Paste at least one API key, one key per line")
    if len(values) > 50:
        raise HTTPException(400, "Add at most 50 keys per save operation")
    existing = db.scalars(select(UserModelCredential).where(
        UserModelCredential.user_id == user_id,
        UserModelCredential.model_id == model_id,
    ).order_by(UserModelCredential.priority.asc(), UserModelCredential.id.asc())).all()
    existing_plain = set()
    for item in existing:
        try:
            existing_plain.add(decrypt_secret(item.secret_encrypted))
        except Exception:
            continue
    next_priority = max((item.priority for item in existing), default=-1) + 1
    added = 0
    seen = set(existing_plain)
    for value in values:
        if value in seen:
            continue
        try:
            encrypted = encrypt_secret(value)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        next_priority += 0
        db.add(UserModelCredential(
            user_id=user_id, model_id=model_id, secret_encrypted=encrypted,
            label=f"Key {next_priority + 1}", priority=next_priority, active=True,
        ))
        seen.add(value)
        next_priority += 1
        added += 1
    if not added:
        raise HTTPException(409, "Those keys are already saved for this customer and model")
    return added


@router.get("/login")
def login_page(request: Request):
    # Backward-compatible URL: all roles now sign in through the customer login page.
    return RedirectResponse("/login", status_code=303)


@router.post("/login")
def legacy_login_post(request: Request):
    return RedirectResponse("/login", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    stats = {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "keys": db.scalar(select(func.count(APIKey.id))) or 0,
        "models": db.scalar(select(func.count(ModelConfig.id)).where(ModelConfig.active.is_(True))) or 0,
        "providers": db.scalar(select(func.count(Provider.id)).where(Provider.active.is_(True))) or 0,
        "pending_orders": db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status.in_(["payment_review", "paid_pending_setup", "provisioning"]))) or 0,
        "pending_payments": db.scalar(select(func.count(PaymentSubmission.id)).where(PaymentSubmission.status == "pending")) or 0,
    }
    return render(request, "dashboard.html", stats=stats)


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    users = db.scalars(select(User).options(joinedload(User.subscriptions).joinedload(Subscription.plan)).order_by(User.id.desc())).unique().all()
    plans = db.scalars(select(Plan).where(Plan.active.is_(True))).all()
    return render(request, "users.html", users=users, plans=plans, message=request.query_params.get("message"))


@router.post("/users")
def create_user(request: Request, username: str = Form(...), password: str = Form(...), plan_id: int = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,29}", username):
        return RedirectResponse("/admin/users?message=invalid_username", status_code=303)
    if len(password) < 10:
        return RedirectResponse("/admin/users?message=weak_password", status_code=303)
    if db.scalar(select(Admin.id).where(func.lower(Admin.username) == username)):
        return RedirectResponse("/admin/users?message=username_reserved", status_code=303)
    if db.scalar(select(User.id).where(func.lower(User.username) == username)):
        return RedirectResponse("/admin/users?message=username_exists", status_code=303)
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(400, "Invalid plan")
    user = User(email=f"acct-{secrets.token_hex(16)}@accounts.alphax.invalid", username=username,
                display_name=username, password_hash=hash_password(password), active=True)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/admin/users?message=username_exists", status_code=303)
    now = datetime.now(timezone.utc)
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", starts_at=now, ends_at=now + timedelta(days=30)))
    db.commit()
    return RedirectResponse(f"/admin/users/{user.id}", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
def user_detail(request: Request, user_id: int, db: Session = Depends(get_db)):
    admin_required(request, db)
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "User not found")
    keys = db.scalars(select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.id.desc())).all()
    subs = db.scalars(select(Subscription).options(joinedload(Subscription.plan)).where(Subscription.user_id == user.id).order_by(Subscription.id.desc())).all()
    today = datetime.now(timezone.utc).date()
    usage = db.scalar(select(UserDailyUsage).where(UserDailyUsage.user_id == user.id, UserDailyUsage.usage_date == today))
    one_time_key = request.session.pop("new_api_key", None)
    plans = db.scalars(select(Plan).where(Plan.active.is_(True))).all()
    models = db.scalars(select(ModelConfig).options(joinedload(ModelConfig.provider)).order_by(ModelConfig.public_name)).all()
    for model in models:
        model.credentials = db.scalars(select(UserModelCredential).where(
            UserModelCredential.user_id == user.id,
            UserModelCredential.model_id == model.id,
        ).order_by(UserModelCredential.priority.asc(), UserModelCredential.id.asc())).all()
        model.credential_configured = any(item.active for item in model.credentials)
    return render(request, "user_detail.html", user=user, keys=keys, subscriptions=subs, usage=usage, new_api_key=one_time_key, plans=plans, models=models)


@router.post("/users/{user_id}/toggle")
def toggle_user(request: Request, user_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    user = db.get(User, user_id)
    if not user: raise HTTPException(404)
    user.active = not user.active; db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/models/{model_id}/credential")
def save_user_model_credential(
    request: Request, user_id: int, model_id: int,
    api_keys_text: str = Form(""), api_key: str = Form(""),
    csrf: str = Form(...), db: Session = Depends(get_db),
):
    admin_required(request, db); check_csrf(request, csrf)
    user = db.get(User, user_id); model = db.get(ModelConfig, model_id)
    if not user or not model:
        raise HTTPException(404, "User or model not found")
    raw_values = api_keys_text or api_key
    added = append_customer_model_keys(db, user_id, model_id, raw_values)
    grant = db.scalar(select(UserModelGrant).where(UserModelGrant.user_id == user_id, UserModelGrant.model_id == model_id))
    if not grant:
        db.add(UserModelGrant(user_id=user_id, model_id=model_id, active=False))
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}?message=credentials_saved&added={added}", status_code=303)


@router.post("/users/{user_id}/models/{model_id}/credentials/{credential_id}/toggle")
def toggle_user_model_credential(request: Request, user_id: int, model_id: int, credential_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    credential = db.get(UserModelCredential, credential_id)
    if not credential or credential.user_id != user_id or credential.model_id != model_id:
        raise HTTPException(404, "Model key not found for this user")
    credential.active = not credential.active
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}?message=credential_status_saved", status_code=303)


@router.post("/keys/{key_id}/toggle")
def toggle_key(request: Request, key_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    key = db.get(APIKey, key_id)
    if not key: raise HTTPException(404)
    if not key.active:
        raise HTTPException(409, "A revoked one-time key cannot be re-enabled. Ask the customer to generate a new AlphaX key.")
    key.active = False
    user_id = key.user_id
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.get("/plans", response_class=HTMLResponse)
def plans_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    plans = db.scalars(select(Plan).order_by(Plan.daily_token_limit)).all()
    return render(request, "plans.html", plans=plans)


@router.post("/plans")
def create_plan(request: Request, name: str = Form(...), daily_token_limit: int = Form(...), price_amount: str = Form("0"), csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    clean_name = name.strip()
    if not clean_name:
        return RedirectResponse("/admin/plans?message=invalid_name", status_code=303)
    if daily_token_limit <= 0:
        return RedirectResponse("/admin/plans?message=invalid_quota", status_code=303)
    if db.scalar(select(Plan.id).where(func.lower(Plan.name) == clean_name.lower())):
        return RedirectResponse("/admin/plans?message=plan_exists", status_code=303)
    try:
        db.add(Plan(name=clean_name, daily_token_limit=daily_token_limit, duration_days=30, price_amount=price_amount.strip(), currency="USDT", active=True))
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/admin/plans?message=plan_exists", status_code=303)
    return RedirectResponse("/admin/plans?message=plan_created", status_code=303)


@router.post("/plans/{plan_id}/update")
def update_plan(request: Request, plan_id: int, name: str = Form(...), daily_token_limit: int = Form(...), price_amount: str = Form("0"), csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    plan = db.get(Plan, plan_id)
    if not plan: raise HTTPException(404)
    if daily_token_limit <= 0: raise HTTPException(400, "Quota must be positive")
    duplicate = db.scalar(select(Plan).where(Plan.name == name.strip(), Plan.id != plan_id))
    if duplicate: raise HTTPException(400, "Plan name already exists")
    plan.name = name.strip(); plan.daily_token_limit = daily_token_limit; plan.price_amount = price_amount
    plan.duration_days = 30; plan.currency = "USDT"
    db.commit()
    return RedirectResponse("/admin/plans", status_code=303)


@router.post("/plans/{plan_id}/toggle")
def toggle_plan(request: Request, plan_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    plan = db.get(Plan, plan_id)
    if not plan: raise HTTPException(404)
    plan.active = not plan.active; db.commit()
    return RedirectResponse("/admin/plans", status_code=303)


@router.post("/users/{user_id}/subscription")
def change_user_subscription(request: Request, user_id: int, plan_id: int = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    user = db.get(User, user_id); plan = db.get(Plan, plan_id)
    if not user or not plan or not plan.active: raise HTTPException(400, "Invalid user or active plan")
    now = datetime.now(timezone.utc)
    current = db.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.status == "active", Subscription.ends_at > now).order_by(Subscription.ends_at.desc()))
    if current:
        current.plan_id = plan.id
    else:
        db.add(Subscription(user_id=user_id, plan_id=plan.id, status="active", starts_at=now, ends_at=now + timedelta(days=30)))
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.get("/providers", response_class=HTMLResponse)
def providers_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    providers = db.scalars(select(Provider).where(Provider.name.in_(["Google AI Studio", "OpenRouter", "APInex", "Regolo"])).order_by(Provider.name)).all()
    return render(request, "providers.html", providers=providers, warning=not bool(settings.fernet_key))


@router.post("/providers")
def create_provider(request: Request, name: str = Form(...), base_url: str = Form(...), protocol: str = Form("google_genai"), csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    raise HTTPException(403, "Only the fixed built-in Google AI Studio, OpenRouter, APInex, and Regolo connectors are supported")


@router.post("/providers/{provider_id}/toggle")
def toggle_provider(request: Request, provider_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    provider = db.get(Provider, provider_id)
    if not provider or provider.name not in {"Google AI Studio", "OpenRouter", "APInex", "Regolo"}:
        raise HTTPException(404, "Provider not found")
    provider.active = not provider.active
    db.commit()
    return RedirectResponse("/admin/providers", status_code=303)


@router.get("/orders", response_class=HTMLResponse)
def orders_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    orders = db.scalars(select(PurchaseOrder).options(joinedload(PurchaseOrder.user), joinedload(PurchaseOrder.plan)).order_by(PurchaseOrder.id.desc())).all()
    return render(request, "orders.html", orders=orders)


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int, db: Session = Depends(get_db)):
    admin_required(request, db)
    order = db.scalar(select(PurchaseOrder).options(joinedload(PurchaseOrder.user), joinedload(PurchaseOrder.plan)).where(PurchaseOrder.id == order_id))
    if not order:
        raise HTTPException(404, "Order not found")
    models = db.scalars(select(ModelConfig).options(joinedload(ModelConfig.provider)).where(ModelConfig.public_id.in_(order.requested_model_ids or [])).order_by(ModelConfig.public_name)).all()
    model_rows = []
    for model in models:
        credentials = db.scalars(select(UserModelCredential).where(
            UserModelCredential.user_id == order.user_id,
            UserModelCredential.model_id == model.id,
        ).order_by(UserModelCredential.priority.asc(), UserModelCredential.id.asc())).all()
        model_rows.append({"model": model, "provider": model.provider, "credentials": credentials,
                           "credential_count": len(credentials),
                           "active_credential_count": sum(1 for item in credentials if item.active),
                           "credential_configured": any(item.active for item in credentials)})
    return render(request, "order_detail.html", order=order, model_rows=model_rows, message=request.query_params.get("message"))


@router.post("/orders/{order_id}/models/{model_id}/credential")
def save_order_model_credential(
    request: Request, order_id: int, model_id: int,
    api_keys_text: str = Form(""), api_key: str = Form(""),
    csrf: str = Form(...), db: Session = Depends(get_db),
):
    admin_required(request, db); check_csrf(request, csrf)
    order = db.get(PurchaseOrder, order_id); model = db.get(ModelConfig, model_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status == "ready":
        return RedirectResponse(f"/admin/orders/{order_id}?message=already_ready", status_code=303)
    if order.status not in {"paid_pending_setup", "provisioning"}:
        return RedirectResponse(f"/admin/orders/{order_id}?message=payment_not_approved", status_code=303)
    if not model or model.public_id not in (order.requested_model_ids or []):
        raise HTTPException(400, "The model is not part of this order")
    added = append_customer_model_keys(db, order.user_id, model_id, api_keys_text or api_key)
    grant = db.scalar(select(UserModelGrant).where(UserModelGrant.user_id == order.user_id, UserModelGrant.model_id == model_id))
    if not grant:
        db.add(UserModelGrant(user_id=order.user_id, model_id=model_id, active=False))
    order.status = "provisioning"
    db.commit()
    return RedirectResponse(f"/admin/orders/{order_id}?message=credentials_saved&added={added}", status_code=303)


@router.post("/orders/{order_id}/complete")
def complete_order_setup(request: Request, order_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status == "ready":
        return RedirectResponse(f"/admin/orders/{order_id}?message=already_ready", status_code=303)
    if order.status not in {"paid_pending_setup", "provisioning"}:
        return RedirectResponse(f"/admin/orders/{order_id}?message=payment_not_approved", status_code=303)
    model_ids = order.requested_model_ids or []
    models = db.scalars(select(ModelConfig).where(ModelConfig.public_id.in_(model_ids))).all()
    if len(models) != len(model_ids):
        raise HTTPException(400, "One or more selected models no longer exist")
    for model in models:
        provider = db.get(Provider, model.provider_id)
        credential = db.scalar(select(UserModelCredential.id).where(
            UserModelCredential.user_id == order.user_id,
            UserModelCredential.model_id == model.id,
            UserModelCredential.active.is_(True),
        ).limit(1))
        if not provider or not provider.active:
            raise HTTPException(409, f"Enable the provider for {model.public_name} before activation")
        if not (model.system_prompt or "").strip():
            raise HTTPException(409, f"Save the System Prompt for {model.public_name} before activation")
        if not credential:
            raise HTTPException(409, f"Add at least one active API key for {model.public_name} in this user's account")
        grant = db.scalar(select(UserModelGrant).where(UserModelGrant.user_id == order.user_id, UserModelGrant.model_id == model.id))
        if not grant:
            db.add(UserModelGrant(user_id=order.user_id, model_id=model.id, active=True))
        else:
            grant.active = True

    subscription = db.get(Subscription, order.subscription_id) if order.subscription_id else None
    if not subscription:
        subscription = db.scalar(select(Subscription).where(Subscription.user_id == order.user_id, Subscription.plan_id == order.plan_id, Subscription.status == "pending_setup").order_by(Subscription.id.desc()))
    if not subscription or subscription.user_id != order.user_id:
        raise HTTPException(409, "The paid subscription record is missing; contact support")
    subscription.status = "active"
    if not subscription.starts_at:
        subscription.starts_at = datetime.now(timezone.utc)
    if not subscription.ends_at:
        subscription.ends_at = subscription.starts_at + timedelta(days=subscription.plan.duration_days or 30)
    order.status = "ready"
    db.commit()
    return RedirectResponse(f"/admin/orders/{order_id}?message=completed", status_code=303)


@router.get("/payments", response_class=HTMLResponse)
def payments_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    methods = db.scalars(select(PaymentMethodSetting).where(PaymentMethodSetting.method != "tcash").order_by(PaymentMethodSetting.id)).all()
    return render(request, "payments.html", methods=methods, warning=not bool(settings.fernet_key))


@router.post("/payments/{method}/save")
def save_manual_payment_method(
    request: Request, method: str, display_name: str = Form(...),
    receiver_code: str = Form(""), instructions: str = Form(""),
    active: str | None = Form(None), csrf: str = Form(...), db: Session = Depends(get_db),
):
    admin_required(request, db); check_csrf(request, csrf)
    setting = db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == method))
    if not setting:
        raise HTTPException(404, "Payment method not found")
    setting.display_name = display_name.strip()[:80]
    setting.receiver_code = receiver_code.strip()[:240]
    setting.instructions = instructions.strip()[:4000]
    setting.active = bool(active) and bool(setting.receiver_code)
    db.commit()
    return RedirectResponse("/admin/payments?saved=1", status_code=303)


@router.get("/payment-reviews", response_class=HTMLResponse)
def payment_reviews_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    submissions = db.scalars(
        select(PaymentSubmission)
        .options(joinedload(PaymentSubmission.user), joinedload(PaymentSubmission.order).joinedload(PurchaseOrder.plan))
        .order_by(case((PaymentSubmission.status == "pending", 0), else_=1), PaymentSubmission.submitted_at.desc())
    ).all()
    try:
        display_tz = ZoneInfo(settings.payment_review_timezone)
    except ZoneInfoNotFoundError:
        display_tz = ZoneInfo("Asia/Damascus")
    for item in submissions:
        paid = item.paid_at.replace(tzinfo=timezone.utc) if item.paid_at.tzinfo is None else item.paid_at
        submitted = item.submitted_at.replace(tzinfo=timezone.utc) if item.submitted_at.tzinfo is None else item.submitted_at
        item.paid_at_display = paid.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        item.submitted_at_display = submitted.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return render(request, "payment_reviews.html", submissions=submissions, message=request.query_params.get("message"), review_timezone=settings.payment_review_timezone)


@router.post("/payment-submissions/{submission_id}/approve")
def approve_payment_submission(
    request: Request, submission_id: int, csrf: str = Form(...),
    admin_note: str = Form(""), db: Session = Depends(get_db),
):
    admin = admin_required(request, db); check_csrf(request, csrf)
    submission = db.get(PaymentSubmission, submission_id)
    if not submission or submission.status != "pending":
        raise HTTPException(409, "Payment submission is no longer pending")
    order = db.get(PurchaseOrder, submission.order_id)
    if not order or order.status != "payment_review":
        raise HTTPException(409, "Order is not waiting for payment review")
    now = datetime.now(timezone.utc)
    submission.status = "approved"
    submission.admin_note = admin_note.strip()[:1000]
    submission.reviewed_at = now
    submission.reviewed_by_admin_id = admin.id
    order.status = "paid_pending_setup"
    order.transaction_id = submission.reference_code
    order.paid_at = submission.paid_at

    if not order.subscription_id:
        pending_subscription = Subscription(
            user_id=order.user_id, plan_id=order.plan_id,
            status="pending_setup", starts_at=None, ends_at=None,
        )
        db.add(pending_subscription); db.flush()
        order.subscription_id = pending_subscription.id
    db.commit()
    return RedirectResponse("/admin/payment-reviews?message=approved", status_code=303)


@router.post("/payment-submissions/{submission_id}/reject")
def reject_payment_submission(
    request: Request, submission_id: int, csrf: str = Form(...),
    admin_note: str = Form(...), db: Session = Depends(get_db),
):
    admin = admin_required(request, db); check_csrf(request, csrf)
    submission = db.get(PaymentSubmission, submission_id)
    if not submission or submission.status != "pending":
        raise HTTPException(409, "Payment submission is no longer pending")
    order = db.get(PurchaseOrder, submission.order_id)
    if not order or order.status != "payment_review":
        raise HTTPException(409, "Order is not waiting for payment review")
    submission.status = "rejected"
    submission.admin_note = admin_note.strip()[:1000] or "Transaction was not confirmed"
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.reviewed_by_admin_id = admin.id
    order.status = "payment_rejected"
    db.commit()
    return RedirectResponse("/admin/payment-reviews?message=rejected", status_code=303)


@router.get("/models", response_class=HTMLResponse)
def models_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    models = db.scalars(select(ModelConfig).options(joinedload(ModelConfig.provider)).order_by(ModelConfig.id.desc())).all()
    for model in models:
        model.public_skills_text = "\n".join(model.public_skills or [])
        rows = []
        for item in (model.public_highlights or []):
            if not isinstance(item, dict):
                continue
            rows.append(" | ".join([
                str(item.get("name", "")), str(item.get("value", "")),
                str(item.get("note", "")), str(item.get("source", "")),
                str(item.get("source_url", "")),
            ]))
        model.public_highlights_text = "\n".join(rows)
    providers = db.scalars(select(Provider).where(Provider.name.in_(["Google AI Studio", "OpenRouter", "APInex", "Regolo"])).order_by(Provider.name)).all()
    return render(request, "models.html", models=models, providers=providers)


@router.post("/models")
def create_model(request: Request, public_id: str = Form(...), public_name: str = Form(...), provider_id: int = Form(...), upstream_model_id: str = Form(...), variants_json: str = Form("[]"), supports_reasoning: str | None = Form(None), reasoning_mode: str = Form("none"), reasoning_parameter: str = Form("thinking_level"), reasoning_options_json: str = Form("{}"), request_defaults_json: str = Form("{}"), fallback_upstream_ids_text: str = Form(""), supports_tools: str | None = Form(None), supports_streaming: str | None = Form("on"), supports_vision: str | None = Form(None), system_prompt: str = Form(""), public_description: str = Form(""), public_skills_text: str = Form(""), public_image: str = Form(""), csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    try:
        variants = json.loads(variants_json or "[]")
        reasoning_options = json.loads(reasoning_options_json or "{}")
        request_defaults = json.loads(request_defaults_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Variants, reasoning options, and request defaults must be valid JSON") from exc
    if not isinstance(variants, list) or not isinstance(reasoning_options, dict) or not isinstance(request_defaults, dict):
        raise HTTPException(400, "Variants must be a list and reasoning options/defaults must be JSON objects")
    public_id_value = public_id.strip().lower()
    public_name_value = public_name.strip()
    upstream_value = upstream_model_id.strip()
    prompt_value = system_prompt.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,119}", public_id_value):
        raise HTTPException(400, "Public model ID must use lowercase letters, numbers, dots, underscores, or hyphens")
    if not public_name_value or len(public_name_value) > 120:
        raise HTTPException(400, "Enter a public model name up to 120 characters")
    if not upstream_value or len(upstream_value) > 200:
        raise HTTPException(400, "Enter the exact upstream model ID for the selected provider")
    if not prompt_value:
        raise HTTPException(400, "A separate System Prompt is required for every model")
    if db.scalar(select(ModelConfig.id).where(ModelConfig.public_id == public_id_value)):
        raise HTTPException(409, "That public model ID already exists")
    fallback_upstream_ids = list(dict.fromkeys(line.strip() for line in fallback_upstream_ids_text.splitlines() if line.strip()))[:10]
    if upstream_value in fallback_upstream_ids:
        raise HTTPException(400, "A fallback model ID must differ from the primary model ID")
    provider = db.get(Provider, provider_id)
    supported_provider = bool(provider and (
        (provider.name == "Google AI Studio" and provider.protocol == "google_genai")
        or (provider.name in {"OpenRouter", "APInex", "Regolo"} and provider.protocol == "openai_compatible")
    ))
    if not supported_provider:
        raise HTTPException(400, "Choose Google AI Studio, OpenRouter, APInex, or Regolo")
    if reasoning_mode not in {"none", "toggle", "levels"}: raise HTTPException(400, "Invalid reasoning mode")
    if supports_reasoning and reasoning_mode == "none": raise HTTPException(400, "Choose toggle or levels for a reasoning model")
    public_skills_text = public_skills_text or ""
    public_skills = [line.strip()[:100] for line in public_skills_text.splitlines() if line.strip()][:40]
    safe_image = (public_image or "").strip()[:500]
    if safe_image and not (safe_image.startswith("/static/") or safe_image.startswith("https://")):
        raise HTTPException(400, "Model image must use /static/ or an HTTPS URL")
    db.add(ModelConfig(
        public_id=public_id_value, public_name=public_name_value, provider_id=provider_id,
        upstream_model_id=upstream_value, system_prompt=prompt_value, reasoning_variants=variants,
        reasoning_options=reasoning_options, request_defaults=request_defaults,
        fallback_upstream_ids=fallback_upstream_ids,
        public_description=(public_description or "").strip()[:12000],
        public_skills=public_skills, public_highlights=[], public_image=safe_image,
        supports_reasoning=bool(supports_reasoning), reasoning_mode=reasoning_mode,
        reasoning_parameter=reasoning_parameter.strip() or "thinking_level",
        supports_tools=bool(supports_tools), supports_streaming=bool(supports_streaming), supports_vision=bool(supports_vision), active=True,
    )); db.commit()
    return RedirectResponse("/admin/models?message=model_added", status_code=303)


@router.post("/models/{model_id}/update")
def update_model(
    request: Request, model_id: int,
    public_id: str = Form(...), public_name: str = Form(...),
    provider_id: int = Form(...), upstream_model_id: str = Form(...),
    reasoning_mode: str = Form("none"), reasoning_parameter: str = Form("reasoning"),
    variants_json: str = Form("[]"), reasoning_options_json: str = Form("{}"), request_defaults_json: str = Form("{}"),
    fallback_upstream_ids_text: str = Form(""), supports_reasoning: str | None = Form(None), supports_tools: str | None = Form(None),
    supports_streaming: str | None = Form(None), supports_vision: str | None = Form(None), active: str | None = Form(None),
    public_description: str = Form(""), public_skills_text: str = Form(""),
    public_highlights_text: str = Form(""), public_image: str = Form(""),
    system_prompt: str = Form(""),
    csrf: str = Form(...), db: Session = Depends(get_db),
):
    admin_required(request, db); check_csrf(request, csrf)
    model = db.get(ModelConfig, model_id); provider = db.get(Provider, provider_id)
    supported_provider = bool(provider and (
        (provider.name == "Google AI Studio" and provider.protocol == "google_genai")
        or (provider.name in {"OpenRouter", "APInex", "Regolo"} and provider.protocol == "openai_compatible")
    ))
    if not model or not supported_provider:
        raise HTTPException(400, "Choose Google AI Studio, OpenRouter, APInex, or Regolo")
    public_id_value = public_id.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,119}", public_id_value):
        raise HTTPException(400, "Public model ID must use lowercase letters, numbers, dots, underscores, or hyphens")
    duplicate = db.scalar(select(ModelConfig.id).where(ModelConfig.public_id == public_id_value, ModelConfig.id != model_id))
    if duplicate:
        raise HTTPException(409, "That public model ID already exists")
    if not public_name.strip() or not upstream_model_id.strip():
        raise HTTPException(400, "Public name and exact upstream model ID are required")
    if not system_prompt.strip():
        raise HTTPException(400, "A separate System Prompt is required for every model")
    if reasoning_mode not in {"none", "toggle", "levels"}: raise HTTPException(400, "Invalid reasoning mode")
    try:
        variants = json.loads(variants_json or "[]")
        options = json.loads(reasoning_options_json or "{}")
        request_defaults = json.loads(request_defaults_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Reasoning JSON is invalid") from exc
    if not isinstance(variants, list) or not isinstance(options, dict) or not isinstance(request_defaults, dict):
        raise HTTPException(400, "Variants must be a list; reasoning options and request defaults must be objects")
    fallback_upstream_ids = list(dict.fromkeys(line.strip() for line in fallback_upstream_ids_text.splitlines() if line.strip()))[:10]
    if any(value == upstream_model_id.strip() for value in fallback_upstream_ids):
        raise HTTPException(400, "A fallback model ID must differ from the primary model ID")
    public_skills = [line.strip()[:100] for line in public_skills_text.splitlines() if line.strip()][:40]
    public_highlights = []
    for line in public_highlights_text.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise HTTPException(400, "Each benchmark line needs at least: name | score")
        parts += [""] * (5 - len(parts))
        source_url = parts[4][:500]
        public_highlights.append({
            "name": parts[0][:100], "value": parts[1][:50], "note": parts[2][:240],
            "source": parts[3][:160], "source_url": source_url,
            "featured": True, "verified": source_url.startswith("https://"),
        })
    public_highlights = public_highlights[:30]
    safe_image = public_image.strip()[:500]
    if safe_image and not (safe_image.startswith("/static/") or safe_image.startswith("https://")):
        raise HTTPException(400, "Model image must use /static/ or an HTTPS URL")
    model.public_id = public_id_value; model.public_name = public_name.strip()
    model.provider_id = provider.id; model.upstream_model_id = upstream_model_id.strip()
    model.system_prompt = system_prompt.strip()
    model.reasoning_mode = reasoning_mode; model.reasoning_parameter = reasoning_parameter.strip() or "reasoning"
    model.reasoning_variants = variants; model.reasoning_options = options; model.request_defaults = request_defaults
    model.fallback_upstream_ids = fallback_upstream_ids
    model.public_description = public_description.strip()[:12000]
    model.public_skills = [x.strip()[:100] for x in public_skills if x.strip()][:40]
    model.public_highlights = public_highlights
    model.public_image = safe_image
    model.supports_reasoning = bool(supports_reasoning); model.supports_tools = bool(supports_tools)
    model.supports_streaming = bool(supports_streaming); model.supports_vision = bool(supports_vision)
    model.active = bool(active)
    db.commit()
    return RedirectResponse("/admin/models", status_code=303)


@router.post("/models/{model_id}/toggle")
def toggle_model(request: Request, model_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    admin_required(request, db); check_csrf(request, csrf)
    m = db.get(ModelConfig, model_id)
    if not m: raise HTTPException(404)
    m.active = not m.active; db.commit()
    return RedirectResponse("/admin/models", status_code=303)


