"""People with accounts, and the phone numbers / emails they sign in with (PRD section 6)."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import CURRENCY_CHECK, Base, CreatedAtMixin, IdMixin, text_enum


class IdentifierKind(StrEnum):
    PHONE = "phone"
    EMAIL = "email"


class User(IdMixin, CreatedAtMixin, Base):
    """No credentials live here: sign-in is by OTP to a user_identifiers row."""

    __tablename__ = "users"

    # Nullable until the "What should friends call you?" screen is done (PRD section 6).
    display_name: Mapped[str | None] = mapped_column(String(80))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    default_currency: Mapped[str | None] = mapped_column(CHAR(3))
    home_country: Mapped[str | None] = mapped_column(CHAR(2))  # ISO 3166 alpha-2

    __table_args__ = (
        CheckConstraint(f"default_currency {CURRENCY_CHECK}", name="default_currency_format"),
        CheckConstraint("home_country ~ '^[A-Z]{2}$'", name="home_country_format"),
        CheckConstraint("char_length(btrim(display_name)) > 0", name="display_name_not_blank"),
    )


class UserIdentifier(IdMixin, CreatedAtMixin, Base):
    """A verified phone (E.164, e.g. +6591234567) or email (lowercased).

    Each phone/email belongs to exactly one account, and an account has at most one of each.
    """

    __tablename__ = "user_identifiers"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[IdentifierKind] = mapped_column(text_enum(IdentifierKind, "identifier_kind"))
    value_normalised: Mapped[str] = mapped_column(Text, unique=True)
    # Rows are only created after an OTP succeeds, so this is always set.
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("user_id", "kind"),
        # At most one primary identifier per user.
        Index(
            "uq_user_identifiers_one_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )
