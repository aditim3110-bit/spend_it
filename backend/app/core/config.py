"""App settings, read from environment variables (or backend/.env).

Every variable is prefixed with SPENDIT_, e.g. SPENDIT_DATABASE_URL.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPENDIT_",
        env_file=".env",
        extra="ignore",
    )

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://spendit:spendit@localhost:5432/spendit"
    redis_url: str = "redis://localhost:6379/0"

    # Used from Milestone 5 (auth). SecretStr keeps it out of logs and error pages.
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-secret")
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=30, gt=0)


@lru_cache
def get_settings() -> Settings:
    """One shared Settings object per process (read the environment once)."""
    return Settings()
