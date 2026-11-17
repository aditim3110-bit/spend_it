"""Friend connections and personal QR codes (PRD section 6A)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, text_enum


class FriendSource(StrEnum):
    QR = "qr"
    PHONE_EMAIL = "phone_email"  # typed their phone number or email
    NEARBY = "nearby"  # Phase 2, Bluetooth "Add nearby"
    CONTACTS = "contacts"
    EXPENSE = "expense"


class Friendship(CreatedAtMixin, Base):
    """A mutual friend connection: exactly one row per pair, smaller user ID first, so
    "Aditi and Ben" and "Ben and Aditi" can't both exist."""

    __tablename__ = "friendships"

    user_a: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    user_b: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    source: Mapped[FriendSource] = mapped_column(text_enum(FriendSource, "friend_source"))

    __table_args__ = (CheckConstraint("user_a < user_b", name="ordered_pair"),)


class UserQrCode(IdMixin, CreatedAtMixin, Base):
    """A user's personal QR code. Stored as-is, since it's meant to be shared like a
    username. "Reset my code" sets revoked_at and creates a new row."""

    __tablename__ = "user_qr_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("code ~ '^[A-Za-z0-9_-]{16,64}$'", name="code_format"),
        # At most one active code per user.
        Index(
            "uq_user_qr_codes_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
