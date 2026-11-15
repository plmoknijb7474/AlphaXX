from sqlalchemy import create_engine, select, func, inspect
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.main import seed_catalog, seed_public_profiles, apply_google_ai_studio_v7_migration, apply_model_assignment_v8_migration
from app.models import ModelConfig, Provider, User, UserModelCredential, UserModelGrant


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)(), engine


def test_seed_catalog_uses_only_google_ai_studio_and_requested_model_ids():
    db, engine = make_db()
    seed_catalog(db); db.commit()
    models = {m.public_id: m for m in db.scalars(select(ModelConfig)).all()}
    assert set(models) == {"y5z-coder-pro", "alphax-pro", "alphax-max"}
    providers = db.scalars(select(Provider)).all()
    assert {p.name for p in providers} == {"Google AI Studio"}
    google = providers[0]
    assert google.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert google.protocol == "google_genai" and google.active is True

    y5z = models["y5z-coder-pro"]
    assert y5z.public_name == "Y5Z Coder Pro"
    assert y5z.upstream_model_id == "gemma-4-26b-a4b-it"
    assert y5z.fallback_upstream_ids == []
    assert y5z.reasoning_options["effort"] == ["minimal", "high"]
    assert y5z.supports_tools and y5z.supports_vision
    assert db.get(Provider, y5z.provider_id).name == "Google AI Studio"

    pro = models["alphax-pro"]
    assert pro.upstream_model_id == "gemini-3.6-flash"
    assert pro.reasoning_options["effort"] == ["minimal", "low", "medium", "high"]
    assert [v["id"] for v in pro.reasoning_variants] == ["minimal", "low", "medium", "high"]
    assert db.get(Provider, pro.provider_id).name == "Google AI Studio"

    max_model = models["alphax-max"]
    assert max_model.upstream_model_id == "gemma-4-31b-it"
    assert max_model.reasoning_options["effort"] == ["minimal", "high"]
    assert db.get(Provider, max_model.provider_id).name == "Google AI Studio"
    assert "model_routes" not in inspect(engine).get_table_names()
    assert "provider_credentials" not in inspect(engine).get_table_names()
    db.close(); engine.dispose()


def test_seed_catalog_does_not_overwrite_admin_customizations():
    db, engine = make_db()
    seed_catalog(db); db.commit()
    model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == "alphax-pro"))
    model.public_name = "AlphaX Pro Custom"
    model.upstream_model_id = "admin-selected-model-id"
    model.system_prompt = "Admin prompt for this model"
    model.fallback_upstream_ids = ["admin/fallback"]
    model.active = False
    db.commit()
    seed_catalog(db); db.commit(); db.refresh(model)
    assert model.public_name == "AlphaX Pro Custom"
    assert model.upstream_model_id == "admin-selected-model-id"
    assert model.system_prompt == "Admin prompt for this model"
    assert model.fallback_upstream_ids == ["admin/fallback"]
    assert model.active is False
    db.close(); engine.dispose()


def test_google_only_migration_reassigns_models_and_disables_incompatible_old_keys():
    db, engine = make_db()
    old_x = Provider(name="xKiro", base_url="https://old-x.invalid/v1", protocol="openai_compatible", active=True)
    old_o = Provider(name="OdiRouter", base_url="https://old-o.invalid/v1", protocol="openai_compatible", active=True)
    google = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    db.add_all([old_x, old_o, google]); db.flush()
    user = User(email="migration@example.test", display_name="Migration")
    db.add(user); db.flush()
    y5z = ModelConfig(public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=old_x.id,
        upstream_model_id="qwen/old-model", active=True, system_prompt="Keep Y5Z prompt")
    pro = ModelConfig(public_id="alphax-pro", public_name="AlphaX Pro", provider_id=old_o.id,
        upstream_model_id="gemini-2.5-pro", active=True, system_prompt="Keep Pro prompt")
    max_model = ModelConfig(public_id="alphax-max", public_name="AlphaX Max", provider_id=google.id,
        upstream_model_id="gemma-4-26b-a4b-it", active=True, system_prompt="Keep Max prompt")
    db.add_all([y5z, pro, max_model]); db.flush()
    db.add_all([
        UserModelGrant(user_id=user.id, model_id=y5z.id, active=True),
        UserModelCredential(user_id=user.id, model_id=y5z.id, secret_encrypted="old-x-key", active=True),
        UserModelCredential(user_id=user.id, model_id=pro.id, secret_encrypted="old-o-key", active=True),
        UserModelCredential(user_id=user.id, model_id=max_model.id, secret_encrypted="google-max-key", active=True),
    ])
    db.commit()

    apply_google_ai_studio_v7_migration(db); db.commit()
    db.refresh(y5z); db.refresh(pro); db.refresh(max_model)
    assert y5z.upstream_model_id == "gemma-4-26b-a4b-it"
    assert pro.upstream_model_id == "gemini-3.6-flash"
    assert max_model.upstream_model_id == "gemma-4-31b-it"
    assert {db.get(Provider, m.provider_id).name for m in (y5z, pro, max_model)} == {"Google AI Studio"}
    assert y5z.system_prompt == "Keep Y5Z prompt"
    assert pro.system_prompt == "Keep Pro prompt"
    assert max_model.system_prompt == "Keep Max prompt"
    assert db.scalar(select(UserModelGrant).where(UserModelGrant.user_id == user.id, UserModelGrant.model_id == y5z.id)).active is True
    creds = db.scalars(select(UserModelCredential).order_by(UserModelCredential.id)).all()
    assert [c.active for c in creds] == [False, False, True]
    assert {p.name for p in db.scalars(select(Provider)).all()} == {"Google AI Studio"}
    db.close(); engine.dispose()


def test_public_profiles_keep_fake_names_only():
    db, engine = make_db()
    seed_catalog(db); seed_public_profiles(db); db.commit()
    models = db.scalars(select(ModelConfig)).all()
    forbidden = ("qwen", "gemini", "gemma", "xkiro", "odirouter", "google ai studio")
    for model in models:
        assert model.public_description and model.public_skills
        assert model.public_image.startswith("/static/images/models/")
        visible_text = (model.public_name + " " + model.public_description + " " + " ".join(model.public_skills)).lower()
        assert not any(name in visible_text for name in forbidden)
        assert not model.public_highlights
    db.close(); engine.dispose()


def test_v8_mapping_moves_y5z_to_26b_and_max_to_31b_without_losing_prompts_or_keys():
    db, engine = make_db()
    google = Provider(name="Google AI Studio", base_url="https://generativelanguage.googleapis.com/v1beta", protocol="google_genai", active=True)
    db.add(google); db.flush()
    user = User(email="v8@example.test", display_name="V8")
    db.add(user); db.flush()
    models = [
        ModelConfig(public_id="y5z-coder-pro", public_name="Y5Z Coder Pro", provider_id=google.id, upstream_model_id="gemma-4-31b-it", active=True, system_prompt="Y5Z prompt", reasoning_options={"effort":["minimal","high"]}, request_defaults={"thinking_level":"high"}),
        ModelConfig(public_id="alphax-pro", public_name="AlphaX Pro", provider_id=google.id, upstream_model_id="gemini-3.6-flash", active=True, system_prompt="Pro prompt"),
        ModelConfig(public_id="alphax-max", public_name="AlphaX Max", provider_id=google.id, upstream_model_id="gemma-4-26b-a4b-it", active=True, system_prompt="Max prompt", reasoning_options={"effort":["minimal","high"]}, request_defaults={"thinking_level":"high"}),
    ]
    db.add_all(models); db.flush()
    for model in models:
        db.add(UserModelCredential(user_id=user.id, model_id=model.id, secret_encrypted=f"enc-{model.public_id}", active=True))
    db.commit()
    prompts = {m.public_id: m.system_prompt for m in models}
    apply_model_assignment_v8_migration(db); db.commit()
    assert {m.public_id: m.upstream_model_id for m in models} == {
        "y5z-coder-pro":"gemma-4-26b-a4b-it",
        "alphax-pro":"gemini-3.6-flash",
        "alphax-max":"gemma-4-31b-it",
    }
    assert {m.public_id: m.system_prompt for m in models} == prompts
    assert db.scalar(select(func.count(UserModelCredential.id)).where(UserModelCredential.user_id == user.id, UserModelCredential.active.is_(True))) == 3
    assert models[1].reasoning_options["effort"] == ["minimal", "low", "medium", "high"]
    db.close(); engine.dispose()
