"""Opaque list cursors (PRD section 17). A cursor is base64 of the sort keys of the last
item on the page, usually (created_at, id). Clients treat it as an opaque string and just
send back the `next_cursor` they were given, so what's inside can differ per list: the
expense feed also carries the expense date, because it is sorted by date first."""

import base64
import json
import uuid
from datetime import date, datetime

from app.core.errors import ProblemError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def _pack(parts: list[str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(parts).encode()).decode().rstrip("=")


def _unpack(cursor: str, n: int) -> list[str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parts = json.loads(base64.urlsafe_b64decode(padded))
    except ValueError:
        raise _invalid() from None
    if not isinstance(parts, list) or len(parts) != n or not all(isinstance(p, str) for p in parts):
        raise _invalid()
    return parts


def _invalid() -> ProblemError:
    return ProblemError(422, "invalid-cursor", "That list cursor isn't valid.")


def encode(created_at: datetime, item_id: uuid.UUID) -> str:
    return _pack([created_at.isoformat(), str(item_id)])


def decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    created_at, item_id = _unpack(cursor, 2)
    try:
        return datetime.fromisoformat(created_at), uuid.UUID(item_id)
    except ValueError:
        raise _invalid() from None


def encode_dated(day: date, created_at: datetime, item_id: uuid.UUID) -> str:
    """For lists sorted by a date first (the expense feed)."""
    return _pack([day.isoformat(), created_at.isoformat(), str(item_id)])


def decode_dated(cursor: str) -> tuple[date, datetime, uuid.UUID]:
    day, created_at, item_id = _unpack(cursor, 3)
    try:
        return date.fromisoformat(day), datetime.fromisoformat(created_at), uuid.UUID(item_id)
    except ValueError:
        raise _invalid() from None
