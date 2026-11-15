import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.database import Base, get_db
from app.models import Admin, User
from app.routers.customer import router as customer_router
from app.security import hash_password


def build_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        db.add(Admin(username="admin", password_hash=hash_password("StrongAdminPass123!"), active=True))
        db.add(User(email="customer@accounts.alphax.invalid", username="customer", display_name="customer",
                    password_hash=hash_password("StrongCustomerPass123!"), active=True))
        db.commit()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-session-secret-key-which-is-long-enough")
    app.include_router(customer_router)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/test/session")
    def session_state(request: Request):
        return {"admin_id": request.session.get("admin_id"), "user_id": request.session.get("user_id")}

    return engine, Session, TestClient(app)


def csrf_from(client, path="/login"):
    page = client.get(path)
    assert page.status_code == 200
    assert 'name="email"' not in page.text
    assert 'name="username"' in page.text
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_shared_username_login_admin_and_customer_and_distinct_errors():
    engine, Session, client = build_client()
    try:
        csrf = csrf_from(client)
        admin_response = client.post("/login", data={
            "username": "admin", "password": "StrongAdminPass123!", "csrf": csrf,
        }, follow_redirects=False)
        assert admin_response.status_code == 303
        assert admin_response.headers["location"] == "/admin"
        assert client.get("/test/session").json()["admin_id"] == 1

        client.cookies.clear()
        csrf = csrf_from(client)
        customer_response = client.post("/login", data={
            "username": "customer", "password": "StrongCustomerPass123!", "csrf": csrf,
        }, follow_redirects=False)
        assert customer_response.status_code == 303
        assert customer_response.headers["location"] == "/account"
        assert client.get("/test/session").json()["user_id"] == 1

        client.cookies.clear()
        csrf = csrf_from(client)
        wrong_password = client.post("/login", data={
            "username": "customer", "password": "WrongPassword123!", "csrf": csrf,
        })
        assert "Incorrect username or password." in wrong_password.text

        client.cookies.clear()
        csrf = csrf_from(client)
        missing = client.post("/login", data={
            "username": "notregistered", "password": "SomePassword123!", "csrf": csrf,
        })
        assert "Account not found. Please create a new account." in missing.text
    finally:
        client.close()
        engine.dispose()


def test_registration_uses_only_username_and_password_and_rejects_duplicates():
    engine, Session, client = build_client()
    try:
        csrf = csrf_from(client, "/register")
        response = client.post("/register", data={
            "username": "new_customer", "password": "StrongCustomerPass123!", "csrf": csrf,
        }, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/account"
        account_page = client.get("/account")
        assert account_page.status_code == 200
        with Session() as db:
            new_user = db.scalar(select(User).where(User.username == "new_customer"))
            assert new_user is not None
            assert new_user.email.endswith("@accounts.alphax.invalid")

        client.cookies.clear()
        csrf = csrf_from(client, "/register")
        duplicate = client.post("/register", data={
            "username": "NEW_CUSTOMER", "password": "StrongCustomerPass123!", "csrf": csrf,
        })
        assert "This username is already taken." in duplicate.text

        client.cookies.clear()
        csrf = csrf_from(client, "/register")
        reserved = client.post("/register", data={
            "username": "admin", "password": "StrongCustomerPass123!", "csrf": csrf,
        })
        assert "This username is reserved." in reserved.text
    finally:
        client.close()
        engine.dispose()
