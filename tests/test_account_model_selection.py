from types import SimpleNamespace as NS
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def _model(public_id, public_name, image, description):
    return NS(
        id=1,
        public_id=public_id,
        public_name=public_name,
        reasoning_mode="levels",
        public_image=image,
        public_description=description,
        public_skills=["Coding", "Reasoning"],
        supports_reasoning=True,
        supports_tools=True,
        supports_streaming=True,
        supports_vision=public_id != "y5z-coder-pro",
    )


def test_customer_portal_uses_real_model_profiles_and_four_customer_sections():
    templates = Path(__file__).resolve().parents[1] / "app" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates)), autoescape=True)
    template = env.get_template("account.html")
    models = [
        _model("alphax-max", "AlphaX Max", "/static/images/models/alphax-group-user.webp", "Max profile description"),
        _model("y5z-coder-pro", "Y5Z Coder Pro", "/static/images/models/y5z-coder-pro-user.webp", "Y5Z profile description"),
        _model("alphax-pro", "AlphaX Pro", "/static/images/models/alphax-group-user.webp", "Pro profile description"),
    ]
    html = template.render(
        request=NS(session={}, query_params={}),
        user=NS(display_name="Demo", email="demo@example.com"),
        csrf="csrf-test",
        active_sub=None,
        usage=NS(total_tokens=0, reserved_tokens=0),
        remaining_tokens=0,
        daily_limit=0,
        quota_percent=0,
        request_count_7d=0,
        daily_usage_chart=[{"label": day, "tokens": 0, "height": 4} for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]],
        model_usage_stats=[],
        active_keys=[],
        keys=[],
        grants=[],
        plans=[NS(id=1, name="Pro", daily_token_limit=2_000_000, price_amount="5", currency="USDT", duration_days=30)],
        payment_methods=[NS(method="binance", display_name="Binance")],
        models=models,
        orders=[],
        subscriptions=[],
        revealable_keys=[],
        api_base_url="https://alphax.example/v1",
        can_purchase=True,
    )

    assert 'data-page="api"' in html
    assert 'data-page="usage"' in html
    assert 'data-page="plans"' in html
    assert 'data-page="models"' in html
    assert 'About Models' in html
    assert 'API access is included with your subscription.' in html
    assert 'name="model_ids" value="y5z-coder-pro"' in html
    assert 'name="model_ids" value="alphax-pro"' in html
    assert 'name="model_ids" value="alphax-max"' in html
    assert 'class="model-art model-art-coder"' in html
    assert 'class="model-art model-art-pro"' in html
    assert 'class="model-art model-art-max"' in html
    assert 'A developer workstation showing code on a monitor' in html
    assert 'A glowing neural network with connected nodes' in html
    assert 'A powerful layered AI processor' in html
    assert 'Y5Z profile description' in html and 'Pro profile description' in html and 'Max profile description' in html
    assert 'Model Pricing' not in html
    assert 'OdiRouter' not in html and 'Google AI Studio' not in html and 'xKiro' not in html
    assert 'ADMIN' not in html
