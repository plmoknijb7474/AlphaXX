from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PaymentSubmission, UserDailyPaymentAttempt


def payment_day_window_utc(now: datetime | None = None):
    try:
        tz = ZoneInfo(settings.payment_review_timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Damascus")
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        now_local.date().isoformat(),
    )


def submissions_used_today(db: Session, user_id: int, start_utc: datetime, end_utc: datetime) -> int:
    return db.scalar(select(func.count(PaymentSubmission.id)).where(
        PaymentSubmission.user_id == user_id,
        PaymentSubmission.submitted_at >= start_utc,
        PaymentSubmission.submitted_at < end_utc,
    )) or 0


def reserve_daily_submission_slot(db: Session, user_id: int, day_key: str, limit: int = 2) -> bool:
    """Atomically reserve one daily attempt. Must be committed with its PaymentSubmission."""
    table = UserDailyPaymentAttempt.__table__
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        insert_stmt = pg_insert(table)
    elif dialect == "sqlite":
        insert_stmt = sqlite_insert(table)
    else:
        # Fallback for local/testing dialects without UPSERT support.
        row = db.scalar(select(UserDailyPaymentAttempt).where(
            UserDailyPaymentAttempt.user_id == user_id,
            UserDailyPaymentAttempt.day_key == day_key,
        ).with_for_update())
        if row is None:
            db.add(UserDailyPaymentAttempt(user_id=user_id, day_key=day_key, submissions_count=1))
            db.flush()
            return True
        if row.submissions_count >= limit:
            return False
        row.submissions_count += 1
        db.flush()
        return True

    stmt = insert_stmt.values(user_id=user_id, day_key=day_key, submissions_count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.user_id, table.c.day_key],
        set_={"submissions_count": table.c.submissions_count + 1},
        where=table.c.submissions_count < limit,
    ).returning(table.c.submissions_count)
    reserved = db.execute(stmt).scalar_one_or_none()
    return reserved is not None
