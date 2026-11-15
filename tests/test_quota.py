from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import User, APIKey, UserDailyUsage
from app.services.quota import reserve_user_tokens, settle_reservation, QuotaExceeded
from app.security import create_api_key


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_quota_is_shared_by_all_user_keys():
    db = make_db()
    user = User(email="one@example.test", active=True)
    db.add(user); db.flush()
    for name in ["key-one", "key-two"]:
        raw, prefix, digest = create_api_key()
        db.add(APIKey(user_id=user.id, name=name, prefix=prefix, key_hash=digest, active=True))
    db.commit()
    reserve_user_tokens(db, user.id, 1_000_000, 700_000)
    settle_reservation(db, user.id, 700_000, 650_000)
    reserve_user_tokens(db, user.id, 1_000_000, 350_000)
    usage = db.scalar(select(UserDailyUsage).where(UserDailyUsage.user_id == user.id))
    assert usage.total_tokens == 650_000
    assert usage.reserved_tokens == 350_000
    try:
        reserve_user_tokens(db, user.id, 1_000_000, 1)
        assert False, "Expected quota limit to be enforced at account level"
    except QuotaExceeded:
        pass
    db.close()
