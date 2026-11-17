"""The signed-in user's own profile."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.errors import ProblemError
from app.core.idempotency import idempotency_key_header
from app.db.session import get_session
from app.models import User
from app.schemas.auth import MeOut
from app.schemas.me import MePatchIn

router = APIRouter(tags=["me"])


def me_out(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        display_name=user.display_name,
        default_currency=user.default_currency,
        home_country=user.home_country,
        needs_name=user.display_name is None,
    )


@router.get("/me", response_model=MeOut)
async def get_me(user: CurrentUser) -> MeOut:
    return me_out(user)


@router.patch("/me", response_model=MeOut)
async def update_me(
    body: MePatchIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _key: Annotated[uuid.UUID, Depends(idempotency_key_header)],
) -> MeOut:
    """Change your name, default currency or home country. Used by the
    'What should friends call you?' screen right after sign-up."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ProblemError(422, "validation-error", "Send at least one field to change.")
    for field, value in changes.items():
        setattr(user, field, value)
    await session.commit()
    return me_out(user)
