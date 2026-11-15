import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.database import Base, get_db
from app.models import Admin, Plan, User, Subscription
from app.routers.admin import router as admin_router
from app.security import hash_password


def build_admin_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with Session() as db:
        admin = Admin(username="admin", password_hash=hash_password("StrongAdminPass123!"), active=True)
        plan = Plan(name="Starter", daily_token_limit=100000, duration_days=30, price_amount="0", currency="USDT", active=True)
        db.add_all([admin, plan]); db.commit()
        admin_id, plan_id = admin.id, plan.id

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-session-secret-key-long-enough-for-tests")
    app.include_router(admin_router)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/test/admin-session")
    def set_admin_session(request: Request):
        request.session["admin_id"] = admin_id
        request.session["csrf"] = "test-csrf-token-value"
        return {"ok": True}

    return engine, Session, TestClient(app), plan_id


def test_admin_pages_render_and_create_customer_action_does_not_500():
    engine, Session, client, plan_id = build_admin_client()
    try:
        client.get("/test/admin-session")
        for path in ("/admin", "/admin/users", "/admin/plans", "/admin/providers", "/admin/orders", "/admin/payments", "/admin/payment-reviews", "/admin/models"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code, response.text[:500])

        response = client.post("/admin/users", data={
            "username": "created_from_admin",
            "password": "StrongCustomerPass123!",
            "plan_id": str(plan_id),
            "csrf": "test-csrf-token-value",
        }, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/admin/users/")
        with Session() as db:
            user = db.scalar(select(User).where(User.username == "created_from_admin"))
            assert user is not None
            assert db.scalar(select(Subscription).where(Subscription.user_id == user.id)) is not None

        duplicate_plan = client.post("/admin/plans", data={
            "name": "Starter", "daily_token_limit": "100000", "price_amount": "0",
            "csrf": "test-csrf-token-value",
        }, follow_redirects=False)
        assert duplicate_plan.status_code == 303
        assert duplicate_plan.headers["location"].endswith("message=plan_exists")
    finally:
        client.close()
        engine.dispose()
