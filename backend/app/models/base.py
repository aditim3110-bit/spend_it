"""Shared building blocks for every table."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names, so migrations can drop/rename them reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    """Random UUID primary key. Random (v4) rather than time-ordered (v7) so an ID
    shown to other people doesn't reveal when an account or expense was created."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Reusable CHECK snippets.
CURRENCY_CHECK = "~ '^[A-Z]{3}$'"  # ISO 4217 shape; the actual list lives in shared/currencies.json
MAX_TOTAL = 10**13  # PRD section 7 "Limits"; same value as split_engine.limits.MAX_TOTAL


def exactly_one(a: str, b: str) -> str:
    """CHECK that exactly one of two columns is set (a person is a user OR a guest)."""
    return f"({a} IS NULL) <> ({b} IS NULL)"


def text_enum(cls: type[StrEnum], name: str) -> Enum:
    """Store an enum as text plus a CHECK, not a Postgres ENUM type. Adding a value later is
    then a one-line migration instead of an awkward ALTER TYPE."""
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
    )
