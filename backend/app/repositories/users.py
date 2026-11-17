"""Database queries for users and their phone/email identifiers."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserIdentifier
from app.models.user import IdentifierKind


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def find_by_identifier(session: AsyncSession, value: str) -> User | None:
    stmt = (
        select(User)
        .join(UserIdentifier, UserIdentifier.user_id == User.id)
        .where(UserIdentifier.value_normalised == value)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_with_identifier(session: AsyncSession, kind: IdentifierKind, value: str) -> User:
    """New account, no name yet (the 'What should friends call you?' screen comes next)."""
    user = User()
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            kind=kind,
            value_normalised=value,
            verified_at=datetime.now(UTC),
            is_primary=True,
        )
    )
    await session.flush()
    return user


async def get_users(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    rows = await session.execute(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in rows.scalars()}
