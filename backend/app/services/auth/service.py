"""Sign in, stay signed in, sign out (PRD section 6)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ProblemError
from app.models import Platform, User
from app.models.user import IdentifierKind
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.services.auth import tokens

# Industry-standard "reuse interval": a used refresh token presented again within this
# window is treated as the same phone retrying, not as theft (PRD section 6).
REFRESH_GRACE = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int  # seconds
    refresh_expires_in: int  # seconds


@dataclass(frozen=True, slots=True)
class SignIn:
    user: User
    is_new_user: bool
    tokens: TokenPair


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def sign_in(
        self,
        kind: IdentifierKind,
        value: str,
        client_device_id: str,
        platform: Platform,
    ) -> SignIn:
        """Called after the one-time code was checked. Sign-up and sign-in are the same flow."""
        now = datetime.now(UTC)
        user = await user_repo.find_by_identifier(self._session, value)
        is_new = user is None
        if user is None:
            try:
                async with self._session.begin_nested():
                    user = await user_repo.create_with_identifier(self._session, kind, value)
            except IntegrityError:
                # The same person verified on two devices at the same moment; use the
                # account the other request just created.
                user = await user_repo.find_by_identifier(self._session, value)
                is_new = False
                if user is None:
                    raise

        device_id = await session_repo.upsert_device(
            self._session,
            user_id=user.id,
            client_device_id=client_device_id,
            platform=platform,
            now=now,
        )
        pair = await self._issue(user.id, device_id, uuid.uuid4(), now)
        await self._session.commit()
        return SignIn(user=user, is_new_user=is_new, tokens=pair)

    async def refresh(self, raw_token: str) -> TokenPair:
        now = datetime.now(UTC)
        token = await session_repo.lock_refresh_token(
            self._session, tokens.hash_refresh_token(raw_token)
        )
        if token is None or token.revoked_at is not None or token.expires_at <= now:
            raise _invalid_refresh()

        if token.used_at is not None and now - token.used_at > REFRESH_GRACE:
            # A pass that was already swapped came back: someone may have a copy.
            # Sign out this whole sign-in (thief and owner); the owner signs in again.
            await session_repo.revoke_family(self._session, token.family_id, now)
            await self._session.commit()
            raise ProblemError(
                401,
                "refresh-token-reused",
                "For your security you've been signed out. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if token.used_at is None:
            token.used_at = now
        # else: within the grace period, so just issue another fresh pass.

        pair = await self._issue(token.user_id, token.device_id, token.family_id, now)
        await self._session.commit()
        return pair

    async def sign_out(self, raw_token: str) -> None:
        """Ends this device's sign-in. Quietly does nothing for an unknown token."""
        now = datetime.now(UTC)
        token = await session_repo.lock_refresh_token(
            self._session, tokens.hash_refresh_token(raw_token)
        )
        if token is not None:
            await session_repo.revoke_family(self._session, token.family_id, now)
        await self._session.commit()

    async def _issue(
        self, user_id: uuid.UUID, device_id: uuid.UUID, family_id: uuid.UUID, now: datetime
    ) -> TokenPair:
        s = self._settings
        refresh = tokens.new_refresh_token()
        refresh_ttl = timedelta(days=s.refresh_token_days)
        await session_repo.add_refresh_token(
            self._session,
            user_id=user_id,
            device_id=device_id,
            family_id=family_id,
            token_hash=tokens.hash_refresh_token(refresh),
            expires_at=now + refresh_ttl,
        )
        access = tokens.create_access_token(
            user_id=user_id,
            family_id=family_id,
            device_id=device_id,
            secret=s.jwt_secret.get_secret_value(),
            minutes=s.access_token_minutes,
            now=now,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            access_expires_in=s.access_token_minutes * 60,
            refresh_expires_in=int(refresh_ttl.total_seconds()),
        )


def _invalid_refresh() -> ProblemError:
    return ProblemError(
        401,
        "invalid-refresh-token",
        "Your session has ended. Please sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
