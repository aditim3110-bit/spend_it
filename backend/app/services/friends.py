"""Adding and removing friends (PRD section 6A)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import pagination, rate_limit
from app.core.errors import ProblemError
from app.models import Friendship, FriendSource, User, UserQrCode
from app.models.user import IdentifierKind
from app.repositories import friends as repo
from app.repositories import users as user_repo

CONNECTS_PER_HOUR = 30
# Checks and adds by phone/email share one budget, so nobody can test numbers in bulk.
LOOKUPS_PER_HOUR = 30


@dataclass(frozen=True, slots=True)
class ConnectResult:
    friend: User
    already_friends: bool


@dataclass(frozen=True, slots=True)
class FriendPage:
    items: list[tuple[User, Friendship]]
    next_cursor: str | None


class FriendService:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis

    async def my_code(self, user: User) -> UserQrCode:
        """Your personal QR code, created the first time you open "My code"."""
        _require_name(user)
        code = await repo.active_code(self._session, user.id)
        if code is not None:
            return code
        try:
            async with self._session.begin_nested():
                code = await repo.create_code(self._session, user.id)
        except IntegrityError:
            # Opened "My code" on two devices at once; use the one just created.
            code = await repo.active_code(self._session, user.id)
            if code is None:
                raise
        await self._session.commit()
        return code

    async def reset_code(self, user: User) -> UserQrCode:
        """The old code stops working immediately; existing friends are kept."""
        _require_name(user)
        await repo.revoke_codes(self._session, user.id, datetime.now(UTC))
        code = await repo.create_code(self._session, user.id)
        await self._session.commit()
        return code

    async def connect_by_code(self, user: User, code: str) -> ConnectResult:
        """Scanning someone's code makes you friends instantly. Showing your code is
        the consent (PRD section 6A)."""
        _require_name(user)
        await rate_limit.hit(
            self._redis,
            f"friends:connect:{user.id}",
            CONNECTS_PER_HOUR,
            60 * 60,
            "Too many friend codes scanned. Please wait and try again.",
        )
        owner = await repo.owner_of_active_code(self._session, code)
        if owner is None:
            raise ProblemError(
                404, "code-not-found", "This code isn't valid anymore. Ask for a fresh one."
            )
        if owner.id == user.id:
            raise ProblemError(422, "cannot-add-yourself", "That's your own code.")
        created = await repo.connect(self._session, user.id, owner.id, FriendSource.QR)
        await self._session.commit()
        return ConnectResult(friend=owner, already_friends=not created)

    async def lookup(self, user: User, value: str) -> User | None:
        """Who has this (already normalised) phone/email? Shown as first name and photo
        so the user knows they typed the right person (PRD section 6A)."""
        await self._lookup_budget(user)
        return await user_repo.find_by_identifier(self._session, value)

    async def add_by_identifier(
        self, user: User, kind: IdentifierKind, value: str, invite_url: str
    ) -> ConnectResult:
        """Instant, like Splitwise. If they're not on SpendIt, the app invites them from
        the user's own phone; SpendIt never sends invites itself."""
        _require_name(user)
        await self._lookup_budget(user)
        other = await user_repo.find_by_identifier(self._session, value)
        if other is None:
            noun = "number" if kind is IdentifierKind.PHONE else "email"
            raise ProblemError(
                404,
                "not-on-spendit",
                f"No one with this {noun} is on SpendIt yet. Invite them!",
                errors=[{"invite_url": invite_url}],
            )
        if other.id == user.id:
            raise ProblemError(422, "cannot-add-yourself", "That's your own account.")
        created = await repo.connect(self._session, user.id, other.id, FriendSource.PHONE_EMAIL)
        await self._session.commit()
        return ConnectResult(friend=other, already_friends=not created)

    async def _lookup_budget(self, user: User) -> None:
        await rate_limit.hit(
            self._redis,
            f"friends:lookup:{user.id}",
            LOOKUPS_PER_HOUR,
            60 * 60,
            "Too many phone numbers or emails checked. Please wait and try again.",
        )

    async def remove(self, user: User, friend_id: uuid.UUID) -> None:
        await repo.remove(self._session, user.id, friend_id)
        await self._session.commit()

    async def page(self, user: User, limit: int, cursor: str | None) -> FriendPage:
        after = pagination.decode(cursor) if cursor else None
        rows = await repo.list_friends(self._session, user.id, limit + 1, after)
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if has_more:
            last_user, last_friendship = rows[-1]
            next_cursor = pagination.encode(last_friendship.created_at, last_user.id)
        return FriendPage(items=rows, next_cursor=next_cursor)


def _require_name(user: User) -> None:
    if user.display_name is None:
        raise ProblemError(
            422, "name-required", "Set your name first, so friends know who you are."
        )
