"""Editing your own profile (PATCH /v1/me). Only the fields sent are changed."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.split_engine import currency


class MePatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The app shows grey "Your first name" in this box (PRD section 6).
    display_name: str | None = Field(default=None, max_length=80)
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    home_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")

    @field_validator("display_name")
    @classmethod
    def _tidy_name(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("display_name can't be removed, only changed")
        tidy = " ".join(v.split())  # trim and collapse repeated spaces
        if not tidy:
            raise ValueError("display_name can't be blank")
        return tidy

    @field_validator("default_currency")
    @classmethod
    def _known_currency(cls, v: str | None) -> str | None:
        if v is not None and not currency.is_supported(v):
            raise ValueError(f"{v} is not a supported currency")
        return v
