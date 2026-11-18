"""Database queries for groups, members, invites and join requests (PRD section 9)."""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, GroupInvite, GroupJoinRequest, GroupMember, User
from app.models.group import JoinRequestStatus

# --- Groups -------------------------------------------------------------------------------


async def get(session: AsyncSession, group_id: uuid.UUID, *, lock: bool = False) -> Group | None:
    """`lock=True` holds the group row until commit, so membership changes (two people
    adding or removing at once, say) happen one after the other."""
    stmt = select(Group).where(Group.id == group_id).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def create(session: AsyncSession, **fields: object) -> Group:
    group = Group(id=uuid.uuid4(), **fields)
    session.add(group)
    await session.flush()
    return group


async def my_groups(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    archived: bool,
    limit: int,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[Group]:
    """Groups the person is currently in, newest first."""
    stmt = (
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == user_id, GroupMember.left_at.is_(None))
        .where(Group.archived_at.is_not(None) if archived else Group.archived_at.is_(None))
        .order_by(Group.created_at.desc(), Group.id.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    if after is not None:
        created_at, last_id = after
        stmt = stmt.where(
            or_(
                Group.created_at < created_at,
                and_(Group.created_at == created_at, Group.id < last_id),
            )
        )
    return list((await session.execute(stmt)).scalars())


async def member_counts(session: AsyncSession, group_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not group_ids:
        return {}
    stmt = (
        select(GroupMember.group_id, func.count())
        .where(GroupMember.group_id.in_(group_ids), GroupMember.left_at.is_(None))
        .group_by(GroupMember.group_id)
    )
    return {gid: n for gid, n in (await session.execute(stmt)).all()}


# --- Members ------------------------------------------------------------------------------


async def membership(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> GroupMember | None:
    """The person's current membership, if they're in the group now."""
    stmt = select(GroupMember).where(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id,
        GroupMember.left_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def member_ids(session: AsyncSession, group_id: uuid.UUID) -> set[uuid.UUID]:
    """User IDs of everyone currently in the group."""
    stmt = select(GroupMember.user_id).where(
        GroupMember.group_id == group_id,
        GroupMember.left_at.is_(None),
        GroupMember.user_id.is_not(None),
    )
    return set((await session.execute(stmt)).scalars())  # type: ignore[arg-type]


async def members(session: AsyncSession, group_id: uuid.UUID) -> list[tuple[GroupMember, User]]:
    """Current members, longest-standing first."""
    stmt = (
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id, GroupMember.left_at.is_(None))
        .order_by(GroupMember.joined_at, GroupMember.id)
        .execution_options(populate_existing=True)
    )
    return [(m, u) for m, u in (await session.execute(stmt)).all()]


async def add_member(session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    # The exact moment (not the transaction start), so people added together are still
    # listed in the order they were added.
    joined = datetime.now(UTC)
    session.add(GroupMember(group_id=group_id, user_id=user_id, joined_at=joined))
    await session.flush()


# --- Invites ------------------------------------------------------------------------------


async def create_invite(
    session: AsyncSession,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    requires_approval: bool,
    expires_at: datetime,
) -> GroupInvite:
    invite = GroupInvite(
        token=secrets.token_urlsafe(16),  # 128 random bits
        group_id=group_id,
        created_by=created_by,
        requires_approval=requires_approval,
        expires_at=expires_at,
    )
    session.add(invite)
    await session.flush()
    return invite


async def get_invite(session: AsyncSession, token: str) -> GroupInvite | None:
    stmt = (
        select(GroupInvite)
        .where(GroupInvite.token == token)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# --- Join requests ------------------------------------------------------------------------


async def pending_request(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> GroupJoinRequest | None:
    stmt = select(GroupJoinRequest).where(
        GroupJoinRequest.group_id == group_id,
        GroupJoinRequest.user_id == user_id,
        GroupJoinRequest.status == JoinRequestStatus.PENDING,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_request(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, token: str
) -> GroupJoinRequest:
    request = GroupJoinRequest(
        group_id=group_id, user_id=user_id, invite_token=token, status=JoinRequestStatus.PENDING
    )
    session.add(request)
    await session.flush()
    return request


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> GroupJoinRequest | None:
    stmt = (
        select(GroupJoinRequest)
        .where(GroupJoinRequest.id == request_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def pending_requests(
    session: AsyncSession, group_id: uuid.UUID
) -> list[tuple[GroupJoinRequest, User]]:
    stmt = (
        select(GroupJoinRequest, User)
        .join(User, User.id == GroupJoinRequest.user_id)
        .where(
            GroupJoinRequest.group_id == group_id,
            GroupJoinRequest.status == JoinRequestStatus.PENDING,
        )
        .order_by(GroupJoinRequest.created_at, GroupJoinRequest.id)
        .execution_options(populate_existing=True)
    )
    return [(r, u) for r, u in (await session.execute(stmt)).all()]
