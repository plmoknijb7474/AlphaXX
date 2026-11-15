from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..models import UserDailyUsage


class QuotaExceeded(Exception):
    pass


def utc_date():
    return datetime.now(timezone.utc).date()


def get_usage(db: Session, user_id: int) -> UserDailyUsage:
    day = utc_date()
    row = db.scalar(select(UserDailyUsage).where(
        UserDailyUsage.user_id == user_id,
        UserDailyUsage.usage_date == day,
    ))
    if row is None:
        row = UserDailyUsage(user_id=user_id, usage_date=day, total_tokens=0, reserved_tokens=0)
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
        except IntegrityError:
            # Another request may have created the same user/day row concurrently.
            db.rollback()
            row = db.scalar(select(UserDailyUsage).where(
                UserDailyUsage.user_id == user_id,
                UserDailyUsage.usage_date == day,
            ))
            if row is None:
                raise
    return row


def reserve_user_tokens(db: Session, user_id: int, plan_limit: int, requested_tokens: int) -> UserDailyUsage:
    """Account-level quota reservation shared by ALL of a user's API keys.

    `with_for_update` is effective on PostgreSQL. SQLite is suitable for local development
    only; production deployments should use PostgreSQL for safe concurrent reservations.
    """
    if requested_tokens < 1:
        raise ValueError("requested_tokens must be positive")
    row = get_usage(db, user_id)
    row = db.scalar(select(UserDailyUsage).where(UserDailyUsage.id == row.id).with_for_update())
    if row.total_tokens + row.reserved_tokens + requested_tokens > plan_limit:
        raise QuotaExceeded("User daily quota exceeded")
    row.reserved_tokens += requested_tokens
    db.commit()
    db.refresh(row)
    return row


def settle_reservation(db: Session, user_id: int, reserved: int, actual_tokens: int) -> UserDailyUsage:
    row = get_usage(db, user_id)
    row = db.scalar(select(UserDailyUsage).where(UserDailyUsage.id == row.id).with_for_update())
    row.reserved_tokens = max(0, row.reserved_tokens - reserved)
    row.total_tokens += max(0, actual_tokens)
    db.commit()
    db.refresh(row)
    return row
