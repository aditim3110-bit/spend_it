"""Friends: your QR code, connecting by scanning, removing, and listing (PRD section 6A)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_settings
from app.core import pagination
from app.core.config import Settings
from app.core.idempotency import idempotency_key_header
from app.db.session import get_session
from app.models import User, UserQrCode
from app.schemas.friends import (
    ConnectIn,
    ConnectOut,
    FriendListItem,
    FriendOut,
    FriendPageOut,
    IdentifierIn,
    LookupOut,
    MyCodeOut,
    PersonPreview,
)
from app.services.auth.identity import normalise
from app.services.friends import FriendService

router = APIRouter(tags=["friends"])
IdempotencyKey = Annotated[uuid.UUID, Depends(idempotency_key_header)]


def get_friend_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> FriendService:
    return FriendService(session, request.app.state.redis)


Friends = Annotated[FriendService, Depends(get_friend_service)]


def _code_out(code: UserQrCode, settings: Settings) -> MyCodeOut:
    return MyCodeOut(
        code=code.code,
        url=f"{settings.public_base_url}/u/{code.code}",
        created_at=code.created_at,
    )


def _friend_out(user: User) -> FriendOut:
    return FriendOut(id=user.id, display_name=user.display_name, avatar_url=user.avatar_url)


@router.get("/me/qr", response_model=MyCodeOut)
async def my_code(
    user: CurrentUser, friends: Friends, settings: Annotated[Settings, Depends(get_settings)]
) -> MyCodeOut:
    """Your personal code. The app draws it as a QR code under Friends → "My code"."""
    return _code_out(await friends.my_code(user), settings)


@router.post("/me/qr/reset", response_model=MyCodeOut)
async def reset_code(
    user: CurrentUser,
    friends: Friends,
    settings: Annotated[Settings, Depends(get_settings)],
    _key: IdempotencyKey,
) -> MyCodeOut:
    """ "Reset my code": the old code stops working at once. Friends are kept."""
    return _code_out(await friends.reset_code(user), settings)


@router.post("/friends/connect", response_model=ConnectOut)
async def connect(
    body: ConnectIn, user: CurrentUser, friends: Friends, _key: IdempotencyKey
) -> ConnectOut:
    """Scanned someone's code: you're now friends (instantly, no approval step)."""
    code = body.code.rstrip("/").rsplit("/", 1)[-1]  # accept the full link or just the code
    result = await friends.connect_by_code(user, code)
    return ConnectOut(friend=_friend_out(result.friend), already_friends=result.already_friends)


@router.post("/friends/lookup", response_model=LookupOut)
async def lookup(
    body: IdentifierIn,
    user: CurrentUser,
    friends: Friends,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LookupOut:
    """Is this phone/email on SpendIt? A POST (not GET) so the number stays out of URLs
    and server logs. Changes nothing, so no Idempotency-Key is needed."""
    value = normalise(body.kind, body.value, body.region or settings.default_phone_region)
    other = await friends.lookup(user, value)
    if other is None:
        return LookupOut(on_spendit=False, person=None)
    first = other.display_name.split()[0] if other.display_name else None
    return LookupOut(
        on_spendit=True, person=PersonPreview(first_name=first, avatar_url=other.avatar_url)
    )


@router.post("/friends/add", response_model=ConnectOut)
async def add_by_phone_or_email(
    body: IdentifierIn,
    user: CurrentUser,
    friends: Friends,
    settings: Annotated[Settings, Depends(get_settings)],
    _key: IdempotencyKey,
) -> ConnectOut:
    """Add a friend by their phone number or email. Instant, like Splitwise."""
    value = normalise(body.kind, body.value, body.region or settings.default_phone_region)
    result = await friends.add_by_identifier(user, body.kind, value, settings.public_base_url)
    return ConnectOut(friend=_friend_out(result.friend), already_friends=result.already_friends)


@router.delete("/friends/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_friend(
    friend_id: uuid.UUID, user: CurrentUser, friends: Friends, _key: IdempotencyKey
) -> Response:
    """Removes the connection. Removing someone who isn't a friend also succeeds."""
    await friends.remove(user, friend_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/friends", response_model=FriendPageOut)
async def list_friends(
    user: CurrentUser,
    friends: Friends,
    limit: Annotated[int, Query(ge=1, le=pagination.MAX_LIMIT)] = pagination.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> FriendPageOut:
    """Your friends, newest first. Pass `next_cursor` back as `cursor` for the next page."""
    page = await friends.page(user, limit, cursor)
    return FriendPageOut(
        items=[
            FriendListItem(**_friend_out(u).model_dump(), source=f.source, since=f.created_at)
            for u, f in page.items
        ],
        next_cursor=page.next_cursor,
    )
