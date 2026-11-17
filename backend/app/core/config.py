"""App settings, read from environment variables (or backend/.env).

Every variable is prefixed with SPENDIT_, e.g. SPENDIT_DATABASE_URL.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Deliberately public: refused outside dev by _real_secret_outside_dev below.
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-0123456789"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPENDIT_",
        env_file=".env",
        extra="ignore",
    )

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://spendit:spendit@localhost:5432/spendit"
    redis_url: str = "redis://localhost:6379/0"

    # Auth (PRD section 6). SecretStr keeps the secret out of logs and error pages.
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=30, gt=0)
    # Used for parsing local phone numbers typed without a country code.
    default_phone_region: str = "SG"

    # Public web address: QR links are {public_base_url}/u/<code> (PRD section 6A).
    public_base_url: str = "https://spendit.app"
    # Placeholder until the app is listed; shown on the QR web page for people without SpendIt.
    app_store_url: str = "https://apps.apple.com/"

    # Shown when a returning guest can't confirm their name (PRD section 15).
    # A setting rather than hard-coded, so it can move to a dedicated support inbox later.
    support_email: str = "aditim3110@gmail.com"

    @model_validator(mode="after")
    def _real_secret_outside_dev(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if self.env in ("staging", "prod") and (secret == DEV_JWT_SECRET or len(secret) < 32):
            raise ValueError("Set a real SPENDIT_JWT_SECRET (32+ characters) outside dev.")
        return self


@lru_cache
def get_settings() -> Settings:
    """One shared Settings object per process (read the environment once)."""
    return Settings()
