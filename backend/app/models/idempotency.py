"""Retry tickets (PRD section 5): the app sends an Idempotency-Key with a write. If the same
key arrives again, the server replays the saved response instead of doing the work twice."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class IdempotencyKey(CreatedAtMixin, Base):
    __tablename__ = "idempotency_keys"

    # Scoped per user: two people can't collide even if their phones pick the same UUID.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(512))
    # SHA-256 of the request body: same key with a different body is rejected, not replayed.
    request_hash: Mapped[str] = mapped_column(String(64))
    # Both NULL while the first request is still running (a retry then gets 409).
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_json: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # created + 24 h

    __table_args__ = (
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_format"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),  # for the cleanup job
    )
