from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Alpha API"
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite:///./alpha.db"
    public_base_url: str = ""
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    cookie_secure: bool = False
    fernet_key: str = ""
    daily_quota_timezone: str = "UTC"
    payment_review_timezone: str = "Asia/Damascus"

    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")


settings = Settings()
