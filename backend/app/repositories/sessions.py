"""Database queries for devices and refresh tokens."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, Platform, RefreshToken


async def upsert_device(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    client_device_id: str,
    platform: Platform,
    now: datetime,
) -> uuid.UUID:
    """Create the device on first sign-in; afterwards just update last_seen_at."""
    stmt = (
        insert(Device)
        .values(
            user_id=user_id,
            client_device_id=client_device_id,
            platform=platform,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_devices_user_id_client_device_id",
            set_={"last_seen_at": now, "platform": platform},
        )
        .returning(Device.id)
    )
    return (await session.execute(stmt)).scalar_one()


async def add_refresh_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    family_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
) -> None:
    session.add(
        RefreshToken(
            user_id=user_id,
            device_id=device_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await session.flush()


async def lock_refresh_token(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    """Fetch and lock the row, so two simultaneous refreshes are handled one at a time."""
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
