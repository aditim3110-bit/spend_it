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
    Text,
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
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(exactly_one("user_id", "guest_id"), name="user_xor_guest"),
        CheckConstraint("left_at IS NULL OR left_at >= joined_at", name="left_after_joined"),
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


class GroupInvite(CreatedAtMixin, Base):
    """A shareable "join Bali 2027" link (PRD section 9). The token is 128 random bits.
    Links expire after 14 days and can be revoked. With requires_approval, accepting
    creates a join request that any member can approve, instead of joining straight away."""

    __tablename__ = "group_invites"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    requires_approval: Mapped[bool] = mapped_column(Boolean)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("token ~ '^[A-Za-z0-9_-]{22,}$'", name="token_format"),)


class JoinRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


class GroupJoinRequest(IdMixin, CreatedAtMixin, Base):
    """Someone accepted an approval-required invite and is waiting for a member to approve."""

    __tablename__ = "group_join_requests"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    invite_token: Mapped[str] = mapped_column(ForeignKey("group_invites.token"))
    status: Mapped[JoinRequestStatus] = mapped_column(
        text_enum(JoinRequestStatus, "join_request_status")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL) AND "
            "(decided_at IS NULL) = (decided_by IS NULL)",
            name="decision_fields_match_status",
        ),
        # One open request per person per group.
        Index(
            "uq_group_join_requests_pending",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )
