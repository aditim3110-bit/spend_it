"""/v1/balances: who owes whom (PRD section 8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_session
from app.schemas.balances import (
    AmountOut,
    BalancesOut,
    ContextBalanceOut,
    CurrencyTotalOut,
    PersonBalanceOut,
    PersonDetailOut,
)
from app.services.balances import BalanceService

router = APIRouter(prefix="/balances", tags=["balances"])


def get_balance_service(session: Annotated[AsyncSession, Depends(get_session)]) -> BalanceService:
    return BalanceService(session)


Balances = Annotated[BalanceService, Depends(get_balance_service)]


def _amounts(amounts: dict[str, int]) -> list[AmountOut]:
    return [AmountOut(currency=c, amount_minor=a) for c, a in amounts.items()]


@router.get("", response_model=BalancesOut)
async def my_balances(user: CurrentUser, balances: Balances) -> BalancesOut:
    """Totals you're owed and owe (per currency), then everyone you have money open with.

    Not paginated: it's a summary with totals, and the list only holds people with a
    non-zero balance, which stays short.
    """
    summary = await balances.summary(user)
    return BalancesOut(
        totals=[
            CurrencyTotalOut(currency=c, owed_to_you=owed, you_owe=owe)
            for c, (owed, owe) in summary.totals.items()
        ],
        people=[
            PersonBalanceOut(
                user_id=p.user_id, display_name=p.display_name, amounts=_amounts(p.amounts)
            )
            for p in summary.people
        ],
    )


@router.get("/friends/{user_id}", response_model=PersonDetailOut)
async def balance_with(
    user_id: uuid.UUID, user: CurrentUser, balances: Balances
) -> PersonDetailOut:
    """Your balance with one person, and which context it comes from. Empty when square."""
    detail = await balances.with_person(user, user_id)
    return PersonDetailOut(
        user_id=detail.person.user_id,
        display_name=detail.person.display_name,
        amounts=_amounts(detail.person.amounts),
        contexts=[
            ContextBalanceOut(
                context_type=c.context_type,
                group_id=c.group_id,
                amounts=_amounts({k: v for k, v in sorted(c.amounts.items()) if v}),
            )
            for c in detail.contexts
            if any(c.amounts.values())
        ],
    )
