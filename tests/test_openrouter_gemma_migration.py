from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import apply_gemma_openrouter_v9_migration
from app.models import (
    ModelConfig, Provider, User, UserModelCredential, UserModelGrant,
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session(), engine


def test_v9_routes_only_gemma_models_to_openrouter_and_keeps_gemini_on_google():
    db, engine = _db()
    google = Provider(
        name="Google AI Studio",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        protocol="google_genai",
        active=True,
    )
    db.add(google)
    db.flush()
    user = User(email="migration@example.test", username="migration", display_name="Migration", active=True)
    db.add(user)
    db.flush()

    specs = [
        ("y5z-coder-pro", "gemma-4-26b-a4b-it"),
        ("alphax-max", "gemma-4-31b-it"),
        ("alphax-pro", "gemini-3.6-flash"),
    ]
    models = []
    for public_id, upstream_id in specs:
        model = ModelConfig(
            public_id=public_id,
            public_name=public_id,
            provider_id=google.id,
            upstream_model_id=upstream_id,
            active=True,
            system_prompt=f"Keep prompt for {public_id}",
            supports_reasoning=True,
            reasoning_mode="levels",
            reasoning_options={"supported": True, "effort": ["minimal", "high"]},
            request_defaults={"thinking_level": "high"},
        )
        db.add(model)
        db.flush()
        models.append(model)
        db.add(UserModelGrant(user_id=user.id, model_id=model.id, active=True))
        db.add(UserModelCredential(
            user_id=user.id, model_id=model.id,
            secret_encrypted=f"encrypted-{public_id}", active=True,
        ))
    db.commit()

    apply_gemma_openrouter_v9_migration(db)
    db.commit()

    by_id = {m.public_id: m for m in db.scalars(select(ModelConfig)).all()}
    openrouter = db.scalar(select(Provider).where(Provider.name == "OpenRouter"))
    google_after = db.scalar(select(Provider).where(Provider.name == "Google AI Studio"))
    assert openrouter is not None
    assert openrouter.base_url == "https://openrouter.ai/api/v1"
    assert openrouter.protocol == "openai_compatible"
    assert openrouter.active is True

    assert by_id["y5z-coder-pro"].provider_id == openrouter.id
    assert by_id["y5z-coder-pro"].upstream_model_id == "google/gemma-4-26b-a4b-it:free"
    assert by_id["alphax-max"].provider_id == openrouter.id
    assert by_id["alphax-max"].upstream_model_id == "google/gemma-4-31b-it:free"
    assert by_id["alphax-pro"].provider_id == google_after.id
    assert by_id["alphax-pro"].upstream_model_id == "gemini-3.6-flash"

    creds = db.scalars(select(UserModelCredential).order_by(UserModelCredential.id)).all()
    assert [c.active for c in creds] == [False, False, True]
    assert [c.last_failure_code for c in creds[:2]] == ["PROVIDER_CHANGED", "PROVIDER_CHANGED"]
    assert by_id["y5z-coder-pro"].system_prompt == "Keep prompt for y5z-coder-pro"
    assert by_id["alphax-max"].system_prompt == "Keep prompt for alphax-max"
    assert by_id["alphax-pro"].system_prompt == "Keep prompt for alphax-pro"
    grants = db.scalars(select(UserModelGrant).order_by(UserModelGrant.id)).all()
    assert all(g.active for g in grants)
    assert by_id["y5z-coder-pro"].reasoning_options["effort"] == ["minimal", "high"]

    db.close()
    engine.dispose()
