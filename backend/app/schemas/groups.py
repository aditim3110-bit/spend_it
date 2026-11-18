"""Request and response bodies for groups, members and invites (PRD section 9)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.group import GroupType
from app.services.split_engine import currency

GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _supported(v: str | None) -> str | None:
    if v is not None and not currency.is_supported(v):
        raise ValueError(f"{v} is not a supported currency")
    return v


# --- In -----------------------------------------------------------------------------------


class GroupCreateIn(Strict):
    name: GroupName
    type: GroupType
    default_currency: str = Field(pattern=r"^[A-Z]{3}$")
    # "Smart Settle" (PRD section 8): fewer transfers inside the group. On by default.
    smart_settle: bool = True
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=99)  # your friends

    @field_validator("default_currency")
    @classmethod
    def _known_currency(cls, v: str) -> str:
        return _supported(v)  # type: ignore[return-value]


class GroupPatchIn(Strict):
    """Any member. Only the fields sent are changed."""

    name: GroupName | None = None
    type: GroupType | None = None
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    smart_settle: bool | None = None

    @field_validator("default_currency")
    @classmethod
    def _known_currency(cls, v: str | None) -> str | None:
        return _supported(v)


class AddMembersIn(Strict):
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)  # the adder's friends


class InviteIn(Strict):
    requires_approval: bool = False


# --- Out ----------------------------------------------------------------------------------


class MemberOut(Strict):
    user_id: uuid.UUID
    display_name: str | None
    avatar_url: str | None
    joined_at: datetime


class GroupOut(Strict):
    id: uuid.UUID
    name: str
    type: GroupType
    default_currency: str
    smart_settle: bool
    created_by: uuid.UUID
    created_at: datetime
    archived_at: datetime | None
    members: list[MemberOut]  # current members, longest-standing first


class GroupListItem(Strict):
    id: uuid.UUID
    name: str
    type: GroupType
    default_currency: str
    smart_settle: bool
    archived_at: datetime | None
    member_count: int


class GroupPageOut(Strict):
    items: list[GroupListItem]
    next_cursor: str | None


class InviteOut(Strict):
    token: str
    url: str  # what the app shares: https://spendit.app/join/<token>
    group_id: uuid.UUID
    requires_approval: bool
    expires_at: datetime


class InvitePreviewOut(Strict):
    """What someone sees before tapping Join (no member names until they're in)."""

    group_id: uuid.UUID
    name: str
    type: GroupType
    member_count: int
    requires_approval: bool
    already_member: bool


class AcceptOut(Strict):
    status: Literal["joined", "pending", "already_member"]
    group_id: uuid.UUID
    request_id: uuid.UUID | None  # set when waiting for a member to approve


class JoinRequestOut(Strict):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str | None
    avatar_url: str | None
    created_at: datetime


class JoinRequestListOut(Strict):
    items: list[JoinRequestOut]
