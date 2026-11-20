from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_customer_templates_use_current_assets_to_avoid_stale_cache():
    for name in ("account.html", "customer_auth.html", "key_reveal.html"):
        source = (ROOT / "app" / "templates" / name).read_text()
        assert "v=1.5.11" in source
        assert "v=1.4.0" not in source


def test_admin_layout_uses_compact_navigation_and_current_assets():
    source = (ROOT / "app" / "templates" / "layout.html").read_text()
    assert "/static/style.css?v=1.5.11" in source
    assert "/static/app.js?v=1.5.11" in source
    assert "Subscriptions &amp; Orders" in source
    assert "Models &amp; Prompts" in source
    assert "System settings" in source
    assert "AI Providers</a><a" not in source


def test_supabase_migration_script_is_included_and_preview_first():
    script = ROOT / "scripts" / "migrate_sqlite_to_supabase.py"
    assert script.is_file()
    source = script.read_text()
    assert "--apply" in source
    assert "Target database is not empty" in source


def test_application_version_is_v1511():
    source = (ROOT / "app" / "main.py").read_text()
    assert 'version="1.5.11"' in source



def test_customer_portal_has_only_four_customer_tabs_and_no_provider_details():
    source = (ROOT / "app" / "templates" / "account.html").read_text().lower()
    assert 'data-go="api"' in source
    assert 'data-go="usage"' in source
    assert 'data-go="plans"' in source
    assert 'data-go="models"' in source
    assert "xkiro" not in source and "odirouter" not in source
    assert "google ai studio" not in source


def test_admin_css_contains_integrated_v152_admin_workspace_styles():
    source = (ROOT / "app" / "static" / "style.css").read_text()
    for selector in ("admin-body", ".admin-sidebar", ".admin-primary-nav", ".quick-grid"):
        assert selector in source


def test_admin_provider_page_lists_all_fixed_connectors():
    source = (ROOT / "app" / "templates" / "providers.html").read_text().lower()
    assert "google ai studio" in source
    assert "openrouter" in source
    assert "apinex" in source
    assert "regolo" in source
    assert "each customer and model" in source
    assert "xkiro" not in source and "odirouter" not in source


def test_supabase_connection_helper_is_present_and_updates_env_only_after_validation():
    source = (ROOT / "scripts" / "configure_supabase.py").read_text()
    assert 'getpass("Paste the Supabase PostgreSQL URI (input hidden): ")' in source
    assert "sslmode" in source and "require" in source
    assert "SUPABASE CONNECTION SUCCESSFUL" in source
    assert "Target database is not empty" in (ROOT / "scripts" / "migrate_sqlite_to_supabase.py").read_text()


def test_admin_add_model_form_exposes_individual_prompt_and_provider_model_id():
    source = (ROOT / "app" / "templates" / "models.html").read_text()
    assert 'action="/admin/models"' in source
    assert 'name="upstream_model_id"' in source
    assert 'name="system_prompt"' in source
    assert 'required placeholder="Write the mandatory instructions for this model.' in source
    assert "Google AI Studio" in source and "OpenRouter" in source and "APInex" in source and "Regolo" in source


def test_supabase_uri_normalizer_forces_ssl_and_sqlalchemy_psycopg_driver():
    import importlib.util
    script = ROOT / "scripts" / "configure_supabase.py"
    spec = importlib.util.spec_from_file_location("alphax_configure_supabase", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app_url, test_url, host, port = module.normalize_supabase_uri(
        "postgresql://postgres.projectref:encoded%40pass@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
    )
    assert app_url.startswith("postgresql+psycopg://")
    assert test_url.startswith("postgresql://")
    assert "sslmode=require" in app_url
    assert host.endswith("pooler.supabase.com") and port == 5432
