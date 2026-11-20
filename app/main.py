from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, text
from .config import settings
from .database import Base, engine, SessionLocal, upgrade_schema
from .models import (
    Admin, ModelConfig, Plan, Provider,
    SystemSetting, UserModelGrant, PaymentMethodSetting,
    PurchaseOrder, PaymentSubmission, UserModelCredential,
)
from .security import hash_password
from .routers.admin import router as admin_router
from .routers.api import router as api_router
from .routers.customer import router as customer_router


def _provider(db, name: str, base_url: str, protocol: str) -> Provider:
    provider = db.scalar(select(Provider).where(Provider.name == name))
    if provider is None:
        provider = Provider(name=name, base_url=base_url, protocol=protocol, active=False)
        db.add(provider)
        db.flush()
    # Existing provider settings are Admin-owned and must never be overwritten at startup.
    return provider


def _get_or_create_model(db, canonical_id: str, legacy_ids: list[str], public_name: str, provider: Provider, upstream_id: str, reasoning_mode: str, reasoning_parameter: str, reasoning_options: dict, request_defaults: dict, reasoning_variants: list, supports_tools: bool = True, supports_streaming: bool = True, supports_vision: bool = False):
    model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == canonical_id))
    migrated = False
    if model is None:
        for legacy in legacy_ids:
            model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == legacy))
            if model is not None:
                model.public_id = canonical_id
                model.public_name = public_name
                migrated = True
                break
    if model is None:
        model = ModelConfig(
            public_id=canonical_id, public_name=public_name, provider_id=provider.id,
            upstream_model_id=upstream_id, active=True, supports_tools=supports_tools,
            supports_streaming=supports_streaming, supports_vision=supports_vision, supports_reasoning=(reasoning_mode != "none"),
            reasoning_mode=reasoning_mode, reasoning_parameter=reasoning_parameter,
            reasoning_options=reasoning_options, request_defaults=request_defaults,
            reasoning_variants=reasoning_variants,
        )
        db.add(model)
        db.flush()
        return model

    if migrated:
        # Migration only: normalize the public alias while preserving Admin-owned provider, prompt, and model settings.
        if model.provider_id == provider.id or not model.provider_id:
            model.provider_id = provider.id
        if model.reasoning_mode in (None, "none"):
            model.reasoning_mode = reasoning_mode
            model.reasoning_parameter = reasoning_parameter
            model.reasoning_options = reasoning_options
            model.request_defaults = request_defaults
            model.reasoning_variants = reasoning_variants
            model.supports_reasoning = reasoning_mode != "none"
        if not model.upstream_model_id:
            model.upstream_model_id = upstream_id
    # Do not overwrite custom names, providers, model IDs, System Prompts, or Admin settings on normal boot.
    return model


def seed_catalog(db):
    """Seed initial model records; one-time provider migrations apply built-in routes."""
    google = _provider(db, "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta", "google_genai")
    google.base_url = "https://generativelanguage.googleapis.com/v1beta"
    google.protocol = "google_genai"
    google.active = True

    gemma_levels = {"supported": True, "effort": ["minimal", "high"],
                    "description": "Gemma 4 supports a two-state thinking switch: high enables thinking; minimal disables it."}
    gemma_variants = [
        {"id": "thinking-off", "body": {"thinking_level": "minimal"}},
        {"id": "thinking-on", "body": {"thinking_level": "high"}},
    ]
    y5z = _get_or_create_model(
        db, "y5z-coder-pro", ["alpha-x-pro"], "Y5Z Coder Pro", google,
        "gemma-4-26b-a4b-it", "levels", "thinking_level", gemma_levels,
        {"thinking_level": "high"}, gemma_variants,
        supports_tools=True, supports_vision=True,
    )

    gemini_levels = {"supported": True, "effort": ["minimal", "low", "medium", "high"]}
    gemini_variants = [
        {"id": level, "body": {"thinking_level": level}}
        for level in ("minimal", "low", "medium", "high")
    ]
    gemini = _get_or_create_model(
        db, "alphax-pro", ["gemini-2-5-pro"], "AlphaX Pro", google,
        "gemini-3.6-flash", "levels", "thinking_level", gemini_levels,
        {"thinking_level": "medium"}, gemini_variants,
        supports_tools=True, supports_vision=True,
    )

    gemma = _get_or_create_model(
        db, "alphax-max", [], "AlphaX Max", google, "gemma-4-31b-it",
        "levels", "thinking_level", gemma_levels,
        {"thinking_level": "high"}, gemma_variants,
        supports_tools=True, supports_vision=True,
    )

def seed_public_profiles(db):
    """Seed customer-facing profiles from official descriptions; never expose upstream names."""
    profiles = {
        "y5z-coder-pro": {
            "description": "A high-capability engineering assistant for software development. It helps build interfaces, write and debug code, understand multi-file repositories, and carry out agentic coding tasks with tools when available.",
            "skills": ["Multi-file coding", "Debugging", "Web interface development", "Long-running agentic tasks", "Tool use", "Instruction following", "Workflow automation"],
            "highlights": [],
            "image":"/static/images/models/y5z-coder-pro-user.webp",
        },
        "alphax-pro": {
            "description": "A fast multimodal assistant for analysis, coding, document understanding, and structured problem solving, with adjustable reasoning effort.",
            "skills": ["Fast reasoning", "Coding assistance", "Image understanding", "Document analysis", "Multilingual tasks", "Tool use", "Structured problem solving"],
            "highlights": [],
            "image":"/static/images/models/alphax-group-user.webp",
        },
        "alphax-max": {
            "description": "A multimodal assistant for text and image understanding, document analysis, diagram interpretation, and practical knowledge work.",
            "skills": ["Text and image understanding", "Document analysis", "Diagram interpretation", "Multilingual tasks", "Knowledge work"],
            "highlights": [],
            "image":"/static/images/models/alphax-group-user.webp",
        },
    }
    for public_id, profile in profiles.items():
        model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == public_id))
        if not model:
            continue
        if not model.public_description:
            model.public_description = profile["description"]
        if not model.public_skills:
            model.public_skills = profile["skills"]
        if not model.public_highlights:
            model.public_highlights = profile["highlights"]
        legacy_default_images = {
            "y5z-coder-pro": {"/static/images/models/y5z-coder-pro.webp"},
            "alphax-pro": {"/static/images/models/alphax-pro.webp"},
            "alphax-max": {"/static/images/models/alphax-max.webp"},
        }
        # Replace only the previous built-in artwork. Preserve any image explicitly
        # uploaded/selected by Admin after the migration.
        if not model.public_image or model.public_image in legacy_default_images.get(public_id, set()):
            model.public_image = profile["image"]



def apply_gemma4_v6_migration(db):
    """Set the built-in AlphaX Max route to hosted Gemma 4 without touching custom routes."""
    model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == "alphax-max"))
    if not model:
        return
    provider = db.get(Provider, model.provider_id)
    # Upgrade only the known built-in Google AI Studio route. Leave administrator-
    # configured provider/model IDs untouched.
    if not provider or provider.name != "Google AI Studio":
        return
    if model.upstream_model_id not in {"gemma-3-27b-it", "gemma-4-26b-a4b-it"}:
        return

    model.upstream_model_id = "gemma-4-26b-a4b-it"
    model.supports_reasoning = True
    model.reasoning_mode = "levels"
    model.reasoning_parameter = "thinking_level"
    model.reasoning_options = {
        "supported": True,
        "effort": ["minimal", "high"],
        "description": "Gemma 4 thinking is a two-state switch: high enables thinking; minimal disables it.",
    }
    model.reasoning_variants = [
        {"id": "thinking-off", "body": {"thinking_level": "minimal"}},
        {"id": "thinking-on", "body": {"thinking_level": "high"}},
    ]
    model.request_defaults = {**(model.request_defaults or {}), "thinking_level": "high"}
    model.supports_vision = True
    model.supports_tools = True


def apply_google_ai_studio_v7_migration(db):
    """Move the three built-in aliases to Google AI Studio and retire legacy providers.

    Existing upstream keys for models moved from xKiro/OdiRouter are disabled, not
    deleted: they are incompatible with Google AI Studio. Admins must add Google
    AI Studio keys to those model/customer assignments. Google keys already on
    AlphaX Max remain active. Prompts, grants, subscriptions and customer API keys
    are deliberately preserved.
    """
    google = _provider(db, "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta", "google_genai")
    google.base_url = "https://generativelanguage.googleapis.com/v1beta"
    google.protocol = "google_genai"
    google.active = True
    db.flush()

    gemma_levels = {"supported": True, "effort": ["minimal", "high"],
                    "description": "Gemma 4 thinking: high enables thinking; minimal disables it."}
    gemma_variants = [
        {"id": "thinking-off", "body": {"thinking_level": "minimal"}},
        {"id": "thinking-on", "body": {"thinking_level": "high"}},
    ]
    specs = {
        "y5z-coder-pro": {
            "upstream": "gemma-4-26b-a4b-it", "reasoning_parameter": "thinking_level",
            "reasoning_options": gemma_levels, "reasoning_variants": gemma_variants,
            "request_key": "thinking_level", "default": "high",
            "supports_vision": True, "supports_tools": True,
            "description": "A high-capability engineering assistant for software development. It helps build interfaces, write and debug code, understand multi-file repositories, and carry out agentic coding tasks with tools when available.",
            "skills": ["Multi-file coding", "Debugging", "Repository understanding", "Interface development", "Tool use", "Agentic workflows"],
        },
        "alphax-pro": {
            "upstream": "gemini-3.6-flash", "reasoning_parameter": "thinking_level",
            "reasoning_options": {"supported": True, "effort": ["minimal", "low", "medium", "high"]},
            "reasoning_variants": [
                {"id": level, "body": {"thinking_level": level}}
                for level in ("minimal", "low", "medium", "high")
            ],
            "request_key": "thinking_level", "default": "medium",
            "supports_vision": True, "supports_tools": True,
            "description": "A fast multimodal assistant for analysis, coding, document understanding, and structured problem solving, with adjustable reasoning effort.",
            "skills": ["Fast reasoning", "Coding assistance", "Image understanding", "Document analysis", "Multilingual tasks", "Tool use"],
        },
        "alphax-max": {
            "upstream": "gemma-4-31b-it", "reasoning_parameter": "thinking_level",
            "reasoning_options": gemma_levels, "reasoning_variants": gemma_variants,
            "request_key": "thinking_level", "default": "high",
            "supports_vision": True, "supports_tools": True,
            "description": "A multimodal assistant for text and image understanding, document analysis, diagram interpretation, and practical knowledge work.",
            "skills": ["Text and image understanding", "Document analysis", "Diagram interpretation", "Multilingual tasks", "Knowledge work"],
        },
    }

    old_provider_names = {"xkiro", "odirouter", "openrouter"}
    for model in db.scalars(select(ModelConfig)).all():
        spec = specs.get(model.public_id)
        previous_provider = db.get(Provider, model.provider_id)
        previous_name = (previous_provider.name if previous_provider else "").strip().lower()
        if spec:
            # Old xKiro/OdiRouter secrets must never be sent to Google's API.
            if previous_name in old_provider_names:
                for credential in db.scalars(select(UserModelCredential).where(UserModelCredential.model_id == model.id)).all():
                    credential.active = False
                    credential.last_failure_code = "PROVIDER_CHANGED"
            model.provider_id = google.id
            model.upstream_model_id = spec["upstream"]
            model.fallback_upstream_ids = []
            model.supports_reasoning = True
            model.reasoning_mode = "levels"
            model.reasoning_parameter = spec["reasoning_parameter"]
            model.reasoning_options = spec["reasoning_options"]
            model.reasoning_variants = spec["reasoning_variants"]
            defaults = dict(model.request_defaults or {})
            for stale_key in ("include_reasoning", "alpha_reasoning", "reasoning_effort", "thinking_level"):
                defaults.pop(stale_key, None)
            defaults[spec["request_key"]] = spec["default"]
            model.request_defaults = defaults
            model.supports_vision = spec["supports_vision"]
            model.supports_tools = spec["supports_tools"]
            model.supports_streaming = True
            # Refresh only the built-in public copy; retain the administrator's private System Prompt.
            old_descriptions = {
                "y5z-coder-pro": "An advanced engineering assistant for coding and agentic work. It helps build interfaces, write and debug code, work across multi-file project repositories, and carry out long-running development tasks using tools when available.",
                "alphax-pro": "A multimodal reasoning model designed for complex problems. It understands text, images, audio, and video, and helps analyze large code repositories, perform advanced coding, reason systematically, and work with long contexts.",
            }
            if not model.public_description or model.public_description == old_descriptions.get(model.public_id) or model.public_id == "alphax-max" and not model.public_description:
                model.public_description = spec["description"]
                model.public_skills = spec["skills"]
            if model.public_id == "alphax-pro":
                # Old benchmarks were for Gemini 2.5 Pro and must not be shown for Gemini 3.6 Flash.
                model.public_highlights = [
                    item for item in (model.public_highlights or [])
                    if "Gemini-2-5-Pro-Model-Card.pdf" not in str(item)
                ]
        elif previous_name in old_provider_names:
            # Retire any administrator-added model that depended on a provider being removed.
            model.provider_id = google.id
            model.active = False
            model.fallback_upstream_ids = []
            for credential in db.scalars(select(UserModelCredential).where(UserModelCredential.model_id == model.id)).all():
                credential.active = False
                credential.last_failure_code = "PROVIDER_RETIRED"

    # Legacy connector records are no longer exposed or accepted. Delete only after every
    # model has been reassigned; Provider has no other credential/data ownership.
    for provider in db.scalars(select(Provider)).all():
        if provider.name.strip().lower() in old_provider_names:
            db.delete(provider)

    # Remove Qwen-only customer compatibility hints from the built-in coder alias.
    db.flush()


def apply_model_assignment_v8_migration(db):
    """Correct the built-in public aliases while preserving every Admin-owned setting.

    Y5Z Coder Pro -> Gemma 4 26B A4B IT
    AlphaX Pro -> Gemini 3.6 Flash
    AlphaX Max -> Gemma 4 31B IT

    The credentials are all Google AI Studio credentials at this point, so they remain
    attached to their respective customer/model assignments. System Prompts, grants,
    subscriptions, and customer AlphaX API keys are not modified.
    """
    google = _provider(
        db, "Google AI Studio",
        "https://generativelanguage.googleapis.com/v1beta", "google_genai",
    )
    google.base_url = "https://generativelanguage.googleapis.com/v1beta"
    google.protocol = "google_genai"
    google.active = True

    gemma_options = {
        "supported": True,
        "effort": ["minimal", "high"],
        "description": "Gemma 4 supports minimal (reduced thinking) and high thinking levels.",
    }
    gemma_variants = [
        {"id": "thinking-off", "body": {"thinking_level": "minimal"}},
        {"id": "thinking-on", "body": {"thinking_level": "high"}},
    ]
    gemini_options = {
        "supported": True,
        "effort": ["minimal", "low", "medium", "high"],
        "description": "Gemini 3.6 Flash supports minimal, low, medium, and high thinking levels.",
    }
    gemini_variants = [
        {"id": level, "body": {"thinking_level": level}}
        for level in ("minimal", "low", "medium", "high")
    ]
    assignments = {
        "y5z-coder-pro": ("gemma-4-26b-a4b-it", gemma_options, gemma_variants, "high"),
        "alphax-pro": ("gemini-3.6-flash", gemini_options, gemini_variants, "medium"),
        "alphax-max": ("gemma-4-31b-it", gemma_options, gemma_variants, "high"),
    }
    for public_id, (upstream_id, options, variants, default_level) in assignments.items():
        model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == public_id))
        if not model:
            continue
        model.provider_id = google.id
        model.upstream_model_id = upstream_id
        model.fallback_upstream_ids = []
        model.supports_reasoning = True
        model.reasoning_mode = "levels"
        model.reasoning_parameter = "thinking_level"
        model.reasoning_options = options
        model.reasoning_variants = variants
        defaults = dict(model.request_defaults or {})
        defaults.pop("reasoning_effort", None)
        defaults["thinking_level"] = default_level
        model.request_defaults = defaults
        model.supports_tools = True
        model.supports_streaming = True
        model.supports_vision = True
        # Do not touch public name/ID, System Prompt, prompt text, grants, or credentials.



def apply_gemma_openrouter_v9_migration(db):
    """Route only the two built-in Gemma aliases through OpenRouter.

    AlphaX Pro stays on Google AI Studio. Previous Google credentials for Gemma
    are disabled (never deleted) because they are not valid OpenRouter tokens.
    Customer grants, subscriptions, prompts, and AlphaX gateway API keys remain.
    """
    openrouter = _provider(
        db, "OpenRouter", "https://openrouter.ai/api/v1", "openai_compatible"
    )
    # This is a fixed, first-party connector: do not let stale provider settings
    # redirect customer credentials to an arbitrary host.
    openrouter.base_url = "https://openrouter.ai/api/v1"
    openrouter.protocol = "openai_compatible"
    openrouter.active = True
    db.flush()

    google = db.scalar(select(Provider).where(Provider.name == "Google AI Studio"))
    if google is None:
        google = _provider(
            db, "Google AI Studio",
            "https://generativelanguage.googleapis.com/v1beta", "google_genai",
        )
        google.base_url = "https://generativelanguage.googleapis.com/v1beta"
        google.protocol = "google_genai"
        google.active = True

    gemma_options = {
        "supported": True,
        "effort": ["minimal", "high"],
        "description": "Gemma 4 via OpenRouter: minimal disables reasoning; high requests high reasoning effort.",
    }
    gemma_variants = [
        {"id": "thinking-off", "body": {"thinking_level": "minimal"}},
        {"id": "thinking-on", "body": {"thinking_level": "high"}},
    ]
    assignments = {
        "y5z-coder-pro": "google/gemma-4-26b-a4b-it:free",
        "alphax-max": "google/gemma-4-31b-it:free",
    }
    for public_id, upstream_id in assignments.items():
        model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == public_id))
        if model is None:
            continue
        old_provider = db.get(Provider, model.provider_id)
        already_openrouter = bool(old_provider and old_provider.name == "OpenRouter")
        model.provider_id = openrouter.id
        model.upstream_model_id = upstream_id
        model.fallback_upstream_ids = []
        model.supports_reasoning = True
        model.reasoning_mode = "levels"
        model.reasoning_parameter = "thinking_level"
        model.reasoning_options = dict(gemma_options)
        model.reasoning_variants = list(gemma_variants)
        defaults = dict(model.request_defaults or {})
        for stale_key in ("reasoning_effort", "reasoning", "alpha_reasoning"):
            defaults.pop(stale_key, None)
        defaults["thinking_level"] = "high"
        model.request_defaults = defaults
        model.supports_tools = True
        model.supports_streaming = True
        model.supports_vision = True

        # Google AI Studio keys are not valid OpenRouter keys. Preserve the
        # encrypted records for audit/rollback, but require a fresh OpenRouter key.
        if not already_openrouter:
            credentials = db.scalars(
                select(UserModelCredential).where(UserModelCredential.model_id == model.id)
            ).all()
            for credential in credentials:
                if credential.active:
                    credential.active = False
                    credential.last_failure_code = "PROVIDER_CHANGED"

    db.flush()


def apply_apinex_regolo_v10_migration(db):
    """Move only Y5Z and AlphaX Pro to the requested OpenAI-compatible providers.

    Y5Z uses APInex's documented zero-price DeepSeek V4 Pro route. AlphaX Pro
    uses Regolo's Gemma 4 31B model. AlphaX Max remains on its existing OpenRouter
    Gemma 4 31B free route. Incompatible customer keys are disabled, never deleted.
    """
    apinex = _provider(db, "APInex", "https://api.apinex.bond/v1", "openai_compatible")
    apinex.base_url = "https://api.apinex.bond/v1"
    apinex.protocol = "openai_compatible"
    apinex.active = True

    regolo = _provider(db, "Regolo", "https://api.regolo.ai/v1", "openai_compatible")
    regolo.base_url = "https://api.regolo.ai/v1"
    regolo.protocol = "openai_compatible"
    regolo.active = True
    db.flush()

    provider_routes = {
        "y5z-coder-pro": {
            "provider": apinex,
            "upstream": "free/deepseek-v4-pro-0813",
            "effort": ["low", "medium", "high"],
            "description": "DeepSeek V4 Pro on APInex zero-price free route. Reasoning effort supports low, medium, and high. No paid fallback is configured.",
            "default": "high",
            "vision": False,
        },
        "alphax-pro": {
            "provider": regolo,
            "upstream": "gemma4-31b",
            "effort": ["low", "medium", "high"],
            "description": "Gemma 4 31B hosted by Regolo. Uses reasoning_effort low/medium/high. Free access depends on Regolo's 30-day trial allowance; no paid fallback is configured.",
            "default": "high",
            "vision": True,
        },
    }

    for public_id, spec in provider_routes.items():
        model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == public_id))
        if model is None:
            continue
        old_provider = db.get(Provider, model.provider_id)
        provider_changed = not old_provider or old_provider.name != spec["provider"].name

        model.provider_id = spec["provider"].id
        model.upstream_model_id = spec["upstream"]
        # Explicitly disable all paid/implicit fallback routes for these two models.
        model.fallback_upstream_ids = []
        model.supports_reasoning = True
        model.reasoning_mode = "levels"
        model.reasoning_parameter = "reasoning_effort"
        model.reasoning_options = {
            "supported": True,
            "effort": list(spec["effort"]),
            "description": spec["description"],
        }
        model.reasoning_variants = [
            {"id": level, "body": {"reasoning_effort": level}}
            for level in spec["effort"]
        ]
        defaults = dict(model.request_defaults or {})
        for stale_key in ("thinking_level", "reasoning", "alpha_reasoning"):
            defaults.pop(stale_key, None)
        defaults["reasoning_effort"] = spec["default"]
        model.request_defaults = defaults
        model.supports_tools = True
        model.supports_streaming = True
        model.supports_vision = bool(spec["vision"])

        # Provider API keys are provider-specific. Preserve encrypted old keys for
        # audit/rollback, but disable them until the administrator adds the new key.
        if provider_changed:
            credentials = db.scalars(
                select(UserModelCredential).where(UserModelCredential.model_id == model.id)
            ).all()
            for credential in credentials:
                if credential.active:
                    credential.active = False
                    credential.last_failure_code = "PROVIDER_CHANGED"

    db.flush()


def apply_alphax_max_gemini36_v11_migration(db):
    """Move only AlphaX Max back to Gemini 3.6 Flash on Google AI Studio.

    Y5Z remains on APInex DeepSeek V4 Pro and AlphaX Pro remains on Regolo
    Gemma 4 31B. OpenRouter credentials currently active on AlphaX Max are
    disabled (never deleted). Google AI Studio credentials previously disabled
    by the v9 provider migration are restored for reuse when available.
    """
    google = _provider(
        db, "Google AI Studio",
        "https://generativelanguage.googleapis.com/v1beta", "google_genai",
    )
    google.base_url = "https://generativelanguage.googleapis.com/v1beta"
    google.protocol = "google_genai"
    google.active = True

    model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == "alphax-max"))
    if model is None:
        db.flush()
        return

    previous_provider = db.get(Provider, model.provider_id)
    provider_changed = not previous_provider or previous_provider.name != "Google AI Studio"
    if provider_changed:
        credentials = db.scalars(
            select(UserModelCredential).where(UserModelCredential.model_id == model.id)
            .order_by(UserModelCredential.id)
        ).all()
        # Old Google keys were marked PROVIDER_CHANGED when v9 moved this model
        # to OpenRouter. Restore those old Google keys, but disable current active
        # OpenRouter keys. Never delete any encrypted credential record.
        previously_disabled_google = [
            credential for credential in credentials
            if not credential.active and credential.last_failure_code == "PROVIDER_CHANGED"
        ]
        for credential in credentials:
            if credential.active:
                credential.active = False
                credential.last_failure_code = "PROVIDER_CHANGED"
        for credential in previously_disabled_google:
            credential.active = True
            credential.last_failure_code = ""

    model.provider_id = google.id
    model.upstream_model_id = "gemini-3.6-flash"
    model.fallback_upstream_ids = []
    model.supports_reasoning = True
    model.reasoning_mode = "levels"
    model.reasoning_parameter = "thinking_level"
    model.reasoning_options = {
        "supported": True,
        "effort": ["minimal", "low", "medium", "high"],
        "description": "Gemini 3.6 Flash on Google AI Studio supports minimal, low, medium, and high thinking levels.",
    }
    model.reasoning_variants = [
        {"id": level, "body": {"thinking_level": level}}
        for level in ("minimal", "low", "medium", "high")
    ]
    defaults = dict(model.request_defaults or {})
    for stale_key in ("reasoning_effort", "reasoning", "alpha_reasoning"):
        defaults.pop(stale_key, None)
    defaults["thinking_level"] = "medium"
    model.request_defaults = defaults
    model.supports_tools = True
    model.supports_streaming = True
    model.supports_vision = True
    db.flush()


def apply_y5z_deepseek_reasoning_toggle_v12_migration(db):
    """Expose DeepSeek V4 Pro's real reasoning ON/OFF toggle for Y5Z only.

    Keep the existing APInex route, model, customer credentials, quotas,
    subscriptions, grants, prompts, and the three selectable effort levels.
    """
    model = db.scalar(select(ModelConfig).where(ModelConfig.public_id == "y5z-coder-pro"))
    if model is None:
        db.flush()
        return
    provider = db.get(Provider, model.provider_id)
    if not provider or provider.name.strip().lower() != "apinex":
        # Do not apply APInex-specific controls to a model rerouted by an Admin.
        db.flush()
        return
    if "deepseek" not in (model.upstream_model_id or "").lower():
        db.flush()
        return

    model.supports_reasoning = True
    model.reasoning_mode = "levels"
    model.reasoning_parameter = "reasoning_effort"
    options = dict(model.reasoning_options or {})
    options["supported"] = True
    options["effort"] = ["low", "medium", "high"]
    options["toggle"] = True
    options["description"] = (
        "DeepSeek V4 Pro supports a separate thinking ON/OFF switch, "
        "plus low, medium, and high reasoning effort when thinking is enabled."
    )
    model.reasoning_options = options

    # Retain the three existing effort variants; OpenCode adds its built-in
    # `none` variant from capabilities.reasoning.toggle.
    defaults = dict(model.request_defaults or {})
    defaults["reasoning_effort"] = defaults.get("reasoning_effort") or "high"
    model.request_defaults = defaults
    db.flush()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    upgrade_schema()
    if settings.environment.lower() == "production":
        from cryptography.fernet import Fernet
        if settings.secret_key == "change-me-in-production" or len(settings.secret_key) < 32 or "replace-" in settings.secret_key.lower():
            raise RuntimeError("Set a unique SECRET_KEY (at least 32 random characters) in production")
        if settings.admin_password in {"change-me-now", "", "replace-this-before-running"} or "replace-" in settings.admin_password.lower() or len(settings.admin_password) < 14:
            raise RuntimeError("Set a strong ADMIN_PASSWORD (at least 14 characters) in production")
        if not settings.cookie_secure:
            raise RuntimeError("Set COOKIE_SECURE=true when running behind HTTPS in production")
        try:
            Fernet(settings.fernet_key.encode())
        except Exception as exc:
            raise RuntimeError("Set a valid FERNET_KEY in production") from exc
    db = SessionLocal()
    try:
        admin = db.scalar(select(Admin).where(Admin.username == settings.admin_username))
        if not admin:
            if settings.admin_password in {"change-me-now", ""}:
                raise RuntimeError("Set a strong ADMIN_PASSWORD in .env before starting Alpha API")
            db.add(Admin(username=settings.admin_username, password_hash=hash_password(settings.admin_password), active=True))
        defaults = [("Starter", 1_000_000), ("Pro", 2_000_000), ("Max", 5_000_000)]
        for name, limit in defaults:
            if not db.scalar(select(Plan).where(Plan.name == name)):
                db.add(Plan(name=name, daily_token_limit=limit, duration_days=30, price_amount="0", currency="USDT", active=True))
        # Rename legacy T-Cash payment method to the requested Syriatel Cash label/slug.
        legacy_syriatel = db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == "tcash"))
        current_syriatel = db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == "syriatel_cash"))
        if legacy_syriatel:
            if not current_syriatel:
                # Rename the legacy row and its references when no new canonical row exists.
                db.query(PurchaseOrder).filter(PurchaseOrder.payment_method == "tcash").update({PurchaseOrder.payment_method: "syriatel_cash"})
                db.query(PaymentSubmission).filter(PaymentSubmission.method == "tcash").update({PaymentSubmission.method: "syriatel_cash"})
                legacy_syriatel.method = "syriatel_cash"
                legacy_syriatel.display_name = "Syriatel Cash"
            else:
                # Keep old pending orders resolvable, but hide/disable the legacy method for new purchases.
                legacy_syriatel.display_name = "Syriatel Cash"
                legacy_syriatel.active = False
        payment_methods = [
            ("binance", "Binance", ""),
            ("syriatel_cash", "Syriatel Cash", ""),
            ("sham_cash", "Sham Cash", ""),
        ]
        for method, display_name, instructions in payment_methods:
            if not db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == method)):
                db.add(PaymentMethodSetting(method=method, display_name=display_name, receiver_code="", instructions=instructions, active=False))
            else:
                existing_method = db.scalar(select(PaymentMethodSetting).where(PaymentMethodSetting.method == method))
                if existing_method and existing_method.display_name != display_name:
                    existing_method.display_name = display_name
        db.flush()
        # Run catalog migration once. Later Admin changes (aliases, routes, reasoning, active flags) persist.
        if db.get(SystemSetting, "public_model_catalog_v1") is None:
            seed_catalog(db)
            db.add(SystemSetting(key="public_model_catalog_v1", value="seeded"))
        # V1 populated the initial public profiles. V2 migrates only known built-in
        # artwork to the user's supplied model identity images; Admin-customized
        # profile text and image paths remain untouched.
        if db.get(SystemSetting, "public_model_profiles_v2_user_art") is None:
            seed_public_profiles(db)
            db.add(SystemSetting(key="public_model_profiles_v2_user_art", value="seeded"))
        # V3-V5 historical markers are kept for databases upgraded through older releases;
        # the Google-only V7 migration below is now the authoritative model/provider mapping.
        for marker in ("model_capabilities_v3", "model_catalog_upstreams_v4", "model_catalog_upstreams_v5_odirouter_gemini"):
            if db.get(SystemSetting, marker) is None:
                db.add(SystemSetting(key=marker, value="superseded-by-v7"))
        # V6 moves the built-in AlphaX Max from the old Gemma 3 setting to the
        # verified Gemma 4 26B A4B hosted Gemini API route and its two-state thinking controls.
        if db.get(SystemSetting, "alphax_max_gemma4_26b_a4b_v6") is None:
            apply_gemma4_v6_migration(db)
            db.add(SystemSetting(key="alphax_max_gemma4_26b_a4b_v6", value="seeded"))
        if db.get(SystemSetting, "google_ai_studio_only_model_catalog_v7") is None:
            apply_google_ai_studio_v7_migration(db)
            db.add(SystemSetting(key="google_ai_studio_only_model_catalog_v7", value="seeded"))
        if db.get(SystemSetting, "model_assignment_v8") is None:
            apply_model_assignment_v8_migration(db)
            db.add(SystemSetting(key="model_assignment_v8", value="seeded"))
        # V9 moves only the Gemma models to OpenRouter. Gemini remains on Google AI Studio.
        if db.get(SystemSetting, "gemma_models_openrouter_v9") is None:
            apply_gemma_openrouter_v9_migration(db)
            db.add(SystemSetting(key="gemma_models_openrouter_v9", value="seeded"))
        # V10 routes Y5Z to APInex DeepSeek V4 Pro and AlphaX Pro to Regolo Gemma 4 31B.
        # V11 routes AlphaX Max to Gemini 3.6 Flash on Google AI Studio.
        if db.get(SystemSetting, "apinex_regolo_model_routes_v10") is None:
            apply_apinex_regolo_v10_migration(db)
            db.add(SystemSetting(key="apinex_regolo_model_routes_v10", value="seeded"))
        if db.get(SystemSetting, "alphax_max_gemini36_google_v11") is None:
            apply_alphax_max_gemini36_v11_migration(db)
            db.add(SystemSetting(key="alphax_max_gemini36_google_v11", value="seeded"))
        # V12 adds a genuine DeepSeek reasoning OFF switch while preserving
        # Y5Z's APInex provider, model route, and low/medium/high effort levels.
        if db.get(SystemSetting, "y5z_deepseek_reasoning_toggle_v12") is None:
            apply_y5z_deepseek_reasoning_toggle_v12_migration(db)
            db.add(SystemSetting(key="y5z_deepseek_reasoning_toggle_v12", value="seeded"))
        db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.5.10", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="alpha_session", same_site="strict", https_only=settings.cookie_secure, max_age=60 * 60 * 8)
APP_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(admin_router)
app.include_router(api_router)
app.include_router(customer_router)


@app.get("/health")
def health():
    """Liveness check: confirms the ASGI worker is responding."""
    return {"status": "ok", "service": "alpha-api", "phase": "alphax-apinex-regolo-gemini-deepseek-toggle-v1.5.10"}


@app.get("/health/ready")
def health_ready():
    """Readiness check: confirms the configured database accepts a simple query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        # Do not leak database URLs, credentials, or connection details to the public endpoint.
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "alpha-api", "version": "1.5.10"},
        )
    return {"status": "ready", "service": "alpha-api", "version": "1.5.10"}


@app.get("/", include_in_schema=False)
def home(request: Request):
    if request.session.get("admin_id"):
        destination = "/admin"
    elif request.session.get("user_id"):
        destination = "/account"
    else:
        destination = "/login"
    return RedirectResponse(destination, status_code=303)
