"""Database queries for friendships and QR codes."""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Friendship, FriendSource, User, UserQrCode


def ordered(x: uuid.UUID, y: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (x, y) if x < y else (y, x)


# --- QR codes ---------------------------------------------------------------------------


async def active_code(session: AsyncSession, user_id: uuid.UUID) -> UserQrCode | None:
    stmt = select(UserQrCode).where(UserQrCode.user_id == user_id, UserQrCode.revoked_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_code(session: AsyncSession, user_id: uuid.UUID) -> UserQrCode:
    """A new random 128-bit code (22 URL-safe characters)."""
    row = UserQrCode(user_id=user_id, code=secrets.token_urlsafe(16))
    session.add(row)
    await session.flush()
    return row


async def revoke_codes(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(UserQrCode)
        .where(UserQrCode.user_id == user_id, UserQrCode.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def owner_of_active_code(session: AsyncSession, code: str) -> User | None:
    stmt = (
        select(User)
        .join(UserQrCode, UserQrCode.user_id == User.id)
        .where(UserQrCode.code == code, UserQrCode.revoked_at.is_(None))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# --- Friendships ------------------------------------------------------------------------


async def connect(session: AsyncSession, x: uuid.UUID, y: uuid.UUID, source: FriendSource) -> bool:
    """Create the friendship. Returns False if they were already friends."""
    a, b = ordered(x, y)
    stmt = (
        insert(Friendship)
        .values(user_a=a, user_b=b, source=source)
        .on_conflict_do_nothing()
        .returning(Friendship.user_a)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def connect_many(
    session: AsyncSession, pairs: set[tuple[uuid.UUID, uuid.UUID]], source: FriendSource
) -> None:
    """Create every missing friendship in one statement; existing ones are left alone."""
    rows = [{"user_a": a, "user_b": b, "source": source} for a, b in {ordered(*p) for p in pairs}]
    if rows:
        await session.execute(insert(Friendship).values(rows).on_conflict_do_nothing())


async def friends_among(
    session: AsyncSession, user_id: uuid.UUID, others: set[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of `others` are friends of `user_id`."""
    if not others:
        return set()
    stmt = select(Friendship.user_a, Friendship.user_b).where(
        or_(
            and_(Friendship.user_a == user_id, Friendship.user_b.in_(others)),
            and_(Friendship.user_b == user_id, Friendship.user_a.in_(others)),
        )
    )
    return {b if a == user_id else a for a, b in (await session.execute(stmt)).all()}


async def pairs_among(session: AsyncSession, people: set[uuid.UUID]) -> set[frozenset[uuid.UUID]]:
    """Every friendship between two people in `people`."""
    if len(people) < 2:
        return set()
    stmt = select(Friendship.user_a, Friendship.user_b).where(
        Friendship.user_a.in_(people), Friendship.user_b.in_(people)
    )
    return {frozenset((a, b)) for a, b in (await session.execute(stmt)).all()}


async def remove(session: AsyncSession, x: uuid.UUID, y: uuid.UUID) -> None:
    a, b = ordered(x, y)
    await session.execute(delete(Friendship).where(Friendship.user_a == a, Friendship.user_b == b))


async def list_friends(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[tuple[User, Friendship]]:
    """Newest connections first. `after` is the (created_at, friend id) of the last item
    on the previous page."""
    other = User.id
    stmt = (
        select(User, Friendship)
        .join(
            Friendship,
            or_(
                and_(Friendship.user_a == user_id, Friendship.user_b == other),
                and_(Friendship.user_b == user_id, Friendship.user_a == other),
            ),
        )
        .order_by(Friendship.created_at.desc(), other.desc())
        .limit(limit)
    )
    if after is not None:
        created_at, last_id = after
        stmt = stmt.where(
            or_(
                Friendship.created_at < created_at,
                and_(Friendship.created_at == created_at, other < last_id),
            )
        )
    return [(u, f) for u, f in (await session.execute(stmt)).all()]
