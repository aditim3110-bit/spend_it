"""Opaque list cursors (PRD section 17): base64 of (created_at, id). Clients treat the
cursor as an opaque string and just send back the `next_cursor` they were given."""

import base64
import json
import uuid
from datetime import datetime

from app.core.errors import ProblemError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def encode(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(item_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, item_id = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(created_at), uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise ProblemError(422, "invalid-cursor", "That list cursor isn't valid.") from None
