"""/v1/groups: groups, members, invite links and join requests (PRD section 9)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_settings
from app.core import pagination
from app.core.config import Settings
from app.core.idempotency import idempotency_key_header
from app.db.session import get_session
from app.models import GroupInvite
from app.schemas.groups import (
    AddMembersIn,
    GroupAmountOut,
    GroupBalancesOut,
    GroupCreateIn,
    GroupListItem,
    GroupMemberBalanceOut,
    GroupOut,
    GroupPageOut,
    GroupPatchIn,
    InviteIn,
    InviteOut,
    JoinRequestListOut,
    JoinRequestOut,
    MemberOut,
    TransferOut,
)
from app.services.balances import BalanceService
from app.services.groups import GroupDetail, GroupService

router = APIRouter(prefix="/groups", tags=["groups"])
IdempotencyKey = Annotated[uuid.UUID, Depends(idempotency_key_header)]


def get_group_service(session: Annotated[AsyncSession, Depends(get_session)]) -> GroupService:
    return GroupService(session)


Groups = Annotated[GroupService, Depends(get_group_service)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def group_out(d: GroupDetail) -> GroupOut:
    g = d.group
    return GroupOut(
        id=g.id,
        name=g.name,
        type=g.type,
        default_currency=g.default_currency,
        smart_settle=g.simplify_debts,
        created_by=g.created_by,
        created_at=g.created_at,
        archived_at=g.archived_at,
        members=[
            MemberOut(
                user_id=u.id,
                display_name=u.display_name,
                avatar_url=u.avatar_url,
                joined_at=m.joined_at,
            )
            for m, u in d.members
        ],
    )


def invite_out(invite: GroupInvite, settings: Settings) -> InviteOut:
    return InviteOut(
        token=invite.token,
        url=f"{settings.public_base_url}/join/{invite.token}",
        group_id=invite.group_id,
        requires_approval=invite.requires_approval,
        expires_at=invite.expires_at,
    )


# --- Groups -------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GroupOut)
async def create_group(
    body: GroupCreateIn, user: CurrentUser, groups: Groups, _key: IdempotencyKey
) -> GroupOut:
    """Create a group. `member_ids` must be your friends. Everyone in the group becomes
    friends with each other. Every member is equal: there are no admins."""
    return group_out(await groups.create(user, body))


@router.get("", response_model=GroupPageOut)
async def list_groups(
    user: CurrentUser,
    groups: Groups,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=pagination.MAX_LIMIT)] = pagination.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> GroupPageOut:
    """Groups you're in, newest first. `archived=true` lists the archived ones."""
    page = await groups.page(user, archived=archived, limit=limit, cursor=cursor)
    return GroupPageOut(
        items=[
            GroupListItem(
                id=e.group.id,
                name=e.group.name,
                type=e.group.type,
                default_currency=e.group.default_currency,
                smart_settle=e.group.simplify_debts,
                archived_at=e.group.archived_at,
                member_count=e.member_count,
            )
            for e in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: uuid.UUID, user: CurrentUser, groups: Groups) -> GroupOut:
    return group_out(await groups.get(user, group_id))


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: uuid.UUID, body: GroupPatchIn, user: CurrentUser, groups: Groups, _key: IdempotencyKey
) -> GroupOut:
    """Any member: change the name, type, default currency or Smart Settle."""
    return group_out(await groups.update(user, group_id, body))


@router.post("/{group_id}/archive", response_model=GroupOut)
async def archive_group(
    group_id: uuid.UUID, user: CurrentUser, groups: Groups, _key: IdempotencyKey
) -> GroupOut:
    """Any member: make the group read-only and hide it from the main list."""
    return group_out(await groups.set_archived(user, group_id, True))


@router.post("/{group_id}/unarchive", response_model=GroupOut)
async def unarchive_group(
    group_id: uuid.UUID, user: CurrentUser, groups: Groups, _key: IdempotencyKey
) -> GroupOut:
    return group_out(await groups.set_archived(user, group_id, False))


# --- Members ------------------------------------------------------------------------------


@router.post("/{group_id}/members", response_model=GroupOut)
async def add_members(
    group_id: uuid.UUID,
    body: AddMembersIn,
    user: CurrentUser,
    groups: Groups,
    _key: IdempotencyKey,
) -> GroupOut:
    """Any member can add their own friends."""
    return group_out(await groups.add_members(user, group_id, body.user_ids))


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    user: CurrentUser,
    groups: Groups,
    _key: IdempotencyKey,
) -> Response:
    """Any member can remove someone, or themselves (leave), only at a zero balance."""
    await groups.remove(user, group_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Invites and join requests ------------------------------------------------------------


@router.post("/{group_id}/invites", status_code=status.HTTP_201_CREATED, response_model=InviteOut)
async def create_invite(
    group_id: uuid.UUID,
    body: InviteIn,
    user: CurrentUser,
    groups: Groups,
    settings: AppSettings,
    _key: IdempotencyKey,
) -> InviteOut:
    """A link to share in a chat. Expires in 14 days. With `requires_approval`, a member
    approves each person who uses it."""
    return invite_out(await groups.create_invite(user, group_id, body.requires_approval), settings)


@router.delete("/{group_id}/invites/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    group_id: uuid.UUID, token: str, user: CurrentUser, groups: Groups, _key: IdempotencyKey
) -> Response:
    """Turn a link off. Any member can turn off any of the group's links."""
    await groups.revoke_invite(user, group_id, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{group_id}/join-requests", response_model=JoinRequestListOut)
async def list_join_requests(
    group_id: uuid.UUID, user: CurrentUser, groups: Groups
) -> JoinRequestListOut:
    """People waiting to join through an approval-required link. Any member can answer."""
    rows = await groups.join_requests(user, group_id)
    return JoinRequestListOut(
        items=[
            JoinRequestOut(
                id=r.id,
                user_id=u.id,
                display_name=u.display_name,
                avatar_url=u.avatar_url,
                created_at=r.created_at,
            )
            for r, u in rows
        ]
    )


@router.post("/{group_id}/join-requests/{request_id}/approve", status_code=204)
async def approve_join_request(
    group_id: uuid.UUID,
    request_id: uuid.UUID,
    user: CurrentUser,
    groups: Groups,
    _key: IdempotencyKey,
) -> Response:
    await groups.decide(user, group_id, request_id, approve=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/join-requests/{request_id}/decline", status_code=204)
async def decline_join_request(
    group_id: uuid.UUID,
    request_id: uuid.UUID,
    user: CurrentUser,
    groups: Groups,
    _key: IdempotencyKey,
) -> Response:
    await groups.decide(user, group_id, request_id, approve=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Balances -----------------------------------------------------------------------------


@router.get("/{group_id}/balances", response_model=GroupBalancesOut)
async def group_balances(
    group_id: uuid.UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    view: Literal["simplified", "detailed"] | None = None,
) -> GroupBalancesOut:
    """Who owes whom in the group. `simplified` (the default when Smart Settle is on) lists
    the fewest payments that settle everyone, only between friends; `detailed` lists the
    plain debts."""
    screen = await BalanceService(session).for_group(user, group_id, view)
    return GroupBalancesOut(
        smart_settle=screen.smart_settle,
        view=screen.view,  # type: ignore[arg-type]
        members=[
            GroupMemberBalanceOut(
                user_id=uid,
                display_name=name,
                amounts=[
                    GroupAmountOut(currency=c, amount_minor=a)
                    for c, a in screen.balances.nets.get(uid, {}).items()
                ],
            )
            for uid, name in screen.people
        ],
        transfers=[
            TransferOut(from_user_id=a, to_user_id=b, currency=c, amount_minor=amt)
            for a, b, c, amt in screen.balances.transfers
        ],
    )
