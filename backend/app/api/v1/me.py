"""The signed-in user's own profile. (Editing it, PATCH /me, arrives with the
Idempotency-Key middleware in the next milestone.)"""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.models import User
from app.schemas.auth import MeOut

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
