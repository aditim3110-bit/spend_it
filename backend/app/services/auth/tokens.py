"""Access tokens (the 15-minute "badge") and refresh tokens (the 30-day "renewal pass").

Access tokens are signed JWTs: the server can check them without a database lookup.
Refresh tokens are random strings; only their SHA-256 hash is stored in the database.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
ISSUER = "spendit"
AUDIENCE = "spendit-api"
KEY_ID = "v1"  # lets us rotate the signing key later without breaking every session


class InvalidToken(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    family_id: uuid.UUID  # which sign-in this badge belongs to
    device_id: uuid.UUID


def create_access_token(
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    device_id: uuid.UUID,
    secret: str,
    minutes: int,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "sid": str(family_id),
        "did": str(device_id),
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM, headers={"kid": KEY_ID})


def decode_access_token(token: str, secret: str) -> AccessClaims:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],  # never trust the token's own "alg" header
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "sid", "did"]},
        )
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            family_id=uuid.UUID(claims["sid"]),
            device_id=uuid.UUID(claims["did"]),
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidToken(str(exc)) from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits of randomness


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
