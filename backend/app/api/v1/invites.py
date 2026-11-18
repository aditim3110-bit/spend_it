"""/v1/invites/{token}: opening and accepting a group invite link (PRD section 9)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser
from app.api.v1.groups import Groups
from app.core.idempotency import idempotency_key_header
from app.schemas.groups import AcceptOut, InvitePreviewOut

router = APIRouter(prefix="/invites", tags=["groups"])
IdempotencyKey = Annotated[uuid.UUID, Depends(idempotency_key_header)]


@router.get("/{token}", response_model=InvitePreviewOut)
async def preview_invite(token: str, user: CurrentUser, groups: Groups) -> InvitePreviewOut:
    """What the link is for, before joining: the group's name, type and size."""
    p = await groups.preview(user, token)
    return InvitePreviewOut(
        group_id=p.group.id,
        name=p.group.name,
        type=p.group.type,
        member_count=p.member_count,
        requires_approval=p.invite.requires_approval,
        already_member=p.already_member,
    )


@router.post(
    "/{token}/accept",
    response_model=AcceptOut,
    responses={202: {"model": AcceptOut, "description": "Waiting for a member to approve"}},
)
async def accept_invite(
    token: str, user: CurrentUser, groups: Groups, response: Response, _key: IdempotencyKey
) -> AcceptOut:
    """Join the group (200), or ask to join if the link needs a member's approval (202)."""
    result = await groups.accept(user, token)
    if result.status == "pending":
        response.status_code = status.HTTP_202_ACCEPTED
    return AcceptOut(status=result.status, group_id=result.group_id, request_id=result.request_id)  # type: ignore[arg-type]
