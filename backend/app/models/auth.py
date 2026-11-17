"""Sign-in sessions (PRD section 6): the devices a user is signed in on, and the
"renewal passes" (refresh tokens) that keep them signed in."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, text_enum


class Platform(StrEnum):
    IOS = "ios"
    WEB = "web"


class Device(IdMixin, CreatedAtMixin, Base):
    """One row per (user, phone/browser). Lets us sign out a single device and send pushes."""

    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    # Chosen by the app (identifierForVendor on iOS); only unique per user.
    client_device_id: Mapped[str] = mapped_column(String(128))
    platform: Mapped[Platform] = mapped_column(text_enum(Platform, "platform"))
    apns_token: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "client_device_id"),)


class RefreshToken(IdMixin, CreatedAtMixin, Base):
    """A one-time renewal pass. Only a SHA-256 hash is stored, so a database leak can't be
    used to sign in.

    Every pass issued from one sign-in shares a family_id. If a used pass comes back more
    than 10 seconds after it was used, the whole family is revoked (likely theft).
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_format"),
        # Cleanup job: find expired passes quickly.
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )
