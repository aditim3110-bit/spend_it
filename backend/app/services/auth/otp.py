"""One-time codes (PRD section 6).

Rules: a code lasts 10 minutes and allows 5 guesses. Each phone/email can request 3 codes per
hour, and each IP address 10 per hour. Everything lives in Redis, keyed by a keyed hash
(HMAC) of the phone/email, so Redis never holds raw contact details or raw codes.

Delivery goes through an OtpSender. In dev, codes are printed to the server log; in tests,
they're captured. Real SMS (Twilio Verify) and email senders plug in here later.
"""

import hashlib
import hmac
import logging
import secrets
from typing import Protocol

from redis.asyncio import Redis

from app.core.errors import ProblemError
from app.models.user import IdentifierKind

CODE_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5
SENDS_PER_IDENTIFIER_PER_HOUR = 3
SENDS_PER_IP_PER_HOUR = 10
WINDOW_SECONDS = 60 * 60

log = logging.getLogger("spendit.otp")


def message_text(code: str) -> str:
    """Code first, so iOS detects it for one-tap autofill. The last line is the standard
    origin-bound format: browsers only offer the code on spendit.app, which stops phishing."""
    return f"{code} is your SpendIt code. It expires in 10 minutes.\n\n@spendit.app #{code}"


def email_subject(code: str) -> str:
    return f"{code} is your SpendIt code"


class OtpSender(Protocol):
    async def send(self, kind: IdentifierKind, destination: str, code: str) -> None: ...


class ConsoleSender:
    """Dev only: prints the code to the server log instead of sending it."""

    async def send(self, kind: IdentifierKind, destination: str, code: str) -> None:
        log.warning("OTP for %s %s: %s", kind.value, destination, code)


class FakeSender:
    """Tests: remembers every code it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[IdentifierKind, str, str]] = []

    async def send(self, kind: IdentifierKind, destination: str, code: str) -> None:
        self.sent.append((kind, destination, code))

    def last_code(self) -> str:
        return self.sent[-1][2]


class OtpService:
    def __init__(self, redis: Redis, sender: OtpSender, secret: bytes) -> None:
        self._redis = redis
        self._sender = sender
        self._key = hashlib.sha256(b"spendit-otp:" + secret).digest()

    def _hash(self, value: str) -> str:
        return hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()

    async def send(self, kind: IdentifierKind, destination: str, ip: str) -> None:
        ident = self._hash(destination)
        await self._rate_limit(f"otp:ip:{self._hash(ip)}", SENDS_PER_IP_PER_HOUR)
        await self._rate_limit(f"otp:sends:{ident}", SENDS_PER_IDENTIFIER_PER_HOUR)

        code = f"{secrets.randbelow(10**6):06d}"
        key = f"otp:code:{ident}"
        async with self._redis.pipeline(transaction=True) as pipe:
            # A new code replaces any earlier one and resets the guess counter.
            pipe.delete(key)
            pipe.hset(key, mapping={"code": self._hash(code), "attempts": 0})
            pipe.expire(key, CODE_TTL_SECONDS)
            await pipe.execute()
        await self._sender.send(kind, destination, code)

    async def check(self, destination: str, code: str) -> None:
        """Return quietly if the code is right; raise a problem otherwise."""
        key = f"otp:code:{self._hash(destination)}"
        stored = await self._redis.hget(key, "code")
        if stored is None:
            raise _expired()
        attempts = await self._redis.hincrby(key, "attempts", 1)
        if attempts > MAX_ATTEMPTS:
            await self._redis.delete(key)
            raise _expired()
        if not hmac.compare_digest(stored.decode(), self._hash(code)):
            left = MAX_ATTEMPTS - attempts
            if left == 0:
                await self._redis.delete(key)
                raise _expired()
            raise ProblemError(
                400,
                "invalid-code",
                f"That code isn't right. {left} attempt{'s' if left != 1 else ''} left.",
                errors=[{"attempts_left": left}],
            )
        await self._redis.delete(key)  # each code works once

    async def _rate_limit(self, key: str, limit: int) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS, nx=True)  # window starts at the first request
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
        if count > limit:
            retry_after = max(int(ttl), 1)
            raise ProblemError(
                429,
                "too-many-requests",
                "Too many codes requested. Please wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )


def _expired() -> ProblemError:
    return ProblemError(
        400, "code-expired", "This code has expired or been used up. Please request a new one."
    )
