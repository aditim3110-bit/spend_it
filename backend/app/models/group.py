"""Groups and their members (PRD section 9)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import CURRENCY_CHECK, Base, CreatedAtMixin, IdMixin, exactly_one, text_enum


class GroupType(StrEnum):
    TRIP = "trip"
    HOME = "home"
    COUPLE = "couple"
    EVENT = "event"
    OTHER = "other"


class GroupRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Group(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[GroupType] = mapped_column(text_enum(GroupType, "group_type"))
    default_currency: Mapped[str] = mapped_column(CHAR(3))
    simplify_debts: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"default_currency {CURRENCY_CHECK}", name="default_currency_format"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
    )


class GroupMember(IdMixin, Base):
    """One row per stint in a group. Leaving sets left_at; rejoining adds a new row, so an
    old expense still shows the name of someone who has since left."""

    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guest_identities.id"), index=True
    )
    role: Mapped[GroupRole] = mapped_column(text_enum(GroupRole, "group_role"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(exactly_one("user_id", "guest_id"), name="user_xor_guest"),
        CheckConstraint("left_at IS NULL OR left_at >= joined_at", name="left_after_joined"),
        CheckConstraint("guest_id IS NULL OR role = 'member'", name="guests_are_not_admins"),
        # Someone can't be a current member of the same group twice.
        Index(
            "uq_group_members_active_user",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=text("left_at IS NULL AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_group_members_active_guest",
            "group_id",
            "guest_id",
            unique=True,
            postgresql_where=text("left_at IS NULL AND guest_id IS NOT NULL"),
        ),
    )
