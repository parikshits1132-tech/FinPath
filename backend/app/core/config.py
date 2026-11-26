"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings for FinPath API."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    database_url: str = (
        "postgresql+asyncpg://finpath_app:finpath_app_dev_password@postgres:5432/finpath"
    )
    migration_database_url: str = (
        "postgresql+psycopg://finpath:finpath_dev_password@postgres:5432/finpath"
    )
    jwt_secret_key: str = "dev-only-change-me-before-production-minimum-32-bytes"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
