"""Request and response shapes for sign-in. Unknown fields are rejected (extra="forbid")."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import Platform
from app.models.user import IdentifierKind


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OtpSendIn(Strict):
    kind: IdentifierKind
    value: str = Field(min_length=3, max_length=320)
    # Country used to read a phone number typed without +country code. Defaults to SG.
    region: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")


class OtpSendOut(Strict):
    status: str = "sent"


class DeviceIn(Strict):
    device_id: str = Field(min_length=1, max_length=128)
    platform: Platform


class OtpVerifyIn(OtpSendIn):
    code: str = Field(pattern=r"^\d{6}$")
    device: DeviceIn


class MeOut(Strict):
    id: uuid.UUID
    display_name: str | None
    default_currency: str | None
    home_country: str | None
    # True until the "What should friends call you?" screen is done.
    needs_name: bool


class TokensOut(Strict):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the standard OAuth 2.0 token type, not a secret
    expires_in: int
    refresh_expires_in: int


class SessionOut(TokensOut):
    is_new_user: bool
    user: MeOut


class RefreshIn(Strict):
    refresh_token: str = Field(min_length=10, max_length=200)
