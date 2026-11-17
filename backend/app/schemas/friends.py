"""Shapes for the friends API (PRD section 6A)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import FriendSource
from app.models.user import IdentifierKind


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MyCodeOut(Strict):
    code: str
    url: str  # what the QR code encodes: https://spendit.app/u/<code>
    created_at: datetime


class ConnectIn(Strict):
    # The app may send the scanned link or just the code; both are accepted.
    code: str = Field(min_length=16, max_length=200)


class FriendOut(Strict):
    id: uuid.UUID
    display_name: str | None
    avatar_url: str | None


class ConnectOut(Strict):
    friend: FriendOut
    already_friends: bool


class FriendListItem(FriendOut):
    source: FriendSource
    since: datetime


class FriendPageOut(Strict):
    items: list[FriendListItem]
    next_cursor: str | None


class IdentifierIn(Strict):
    kind: IdentifierKind
    value: str = Field(min_length=3, max_length=320)
    # Country used to read a phone number typed without +country code.
    region: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")


class PersonPreview(Strict):
    """Just enough to confirm it's the right person: first name and photo, nothing else."""

    first_name: str | None
    avatar_url: str | None


class LookupOut(Strict):
    on_spendit: bool
    person: PersonPreview | None
