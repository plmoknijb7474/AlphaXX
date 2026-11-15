from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User, UserDailyPaymentAttempt, PaymentSubmission, PurchaseOrder, Plan
from app.services.manual_payments import reserve_daily_submission_slot, payment_day_window_utc, submissions_used_today


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_only_two_daily_payment_proof_slots_per_user():
    db = make_db()
    user = User(email="payer@example.test", active=True)
    db.add(user); db.flush()
    today = datetime.now(timezone.utc).date().isoformat()
    assert reserve_daily_submission_slot(db, user.id, today, limit=2) is True
    db.commit()
    assert reserve_daily_submission_slot(db, user.id, today, limit=2) is True
    db.commit()
    assert reserve_daily_submission_slot(db, user.id, today, limit=2) is False
    db.rollback()
    counter = db.scalar(select(UserDailyPaymentAttempt).where(UserDailyPaymentAttempt.user_id == user.id))
    assert counter.submissions_count == 2
    db.close()


def test_payment_reference_uniqueness_per_method():
    db = make_db()
    user = User(email="unique@example.test", active=True)
    db.add(user); db.flush()
    plan = Plan(name="Test", daily_token_limit=1_000_000, duration_days=30, price_amount="10", currency="USDT")
    db.add(plan); db.flush()
    order = PurchaseOrder(user_id=user.id, plan_id=plan.id, requested_model_ids=["y5z-coder-pro"], status="payment_review", merchant_trade_no="A1", amount="10", currency="USDT", payment_method="sham_cash")
    db.add(order); db.flush()
    db.add(PaymentSubmission(order_id=order.id, user_id=user.id, method="sham_cash", reference_code="SC-12345", reference_code_normalized="sc-12345", paid_at=datetime.now(timezone.utc), status="pending"))
    db.commit()
    assert db.scalar(select(PaymentSubmission.id).where(PaymentSubmission.method == "sham_cash", PaymentSubmission.reference_code_normalized == "sc-12345")) is not None
    db.close()


def test_payment_day_window_is_valid_utc_range():
    start, end, day_key = payment_day_window_utc(datetime(2026, 11, 11, 12, tzinfo=timezone.utc))
    assert start.tzinfo is not None and end.tzinfo is not None
    assert end > start
    assert len(day_key) == 10
