"""/v1/settlements: recording payments (PRD section 8).

A recorded payment is a ledger entry like an expense (kind "settlement"), so viewing,
deleting, restoring and its history use the /v1/expenses/{id} routes. Only creating and
editing differ, because the body is different.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.expenses import expense_out
from app.core.idempotency import idempotency_key_header
from app.db.session import get_session
from app.schemas.expenses import ExpenseOut
from app.schemas.settlements import SettlementEditIn, SettlementIn
from app.services.settlements import SettlementService

router = APIRouter(prefix="/settlements", tags=["settlements"])
IdempotencyKey = Annotated[uuid.UUID, Depends(idempotency_key_header)]


def get_settlement_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SettlementService:
    return SettlementService(session)


Settlements = Annotated[SettlementService, Depends(get_settlement_service)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ExpenseOut)
async def record_payment(
    body: SettlementIn, user: CurrentUser, settlements: Settlements, _key: IdempotencyKey
) -> ExpenseOut:
    """Record that someone paid someone back. Either of the two can record it, for any
    amount: paying more than is owed means the other person then owes the difference."""
    return expense_out(await settlements.record(user, body))


@router.put("/{expense_id}", response_model=ExpenseOut)
async def edit_payment(
    expense_id: uuid.UUID,
    body: SettlementEditIn,
    user: CurrentUser,
    settlements: Settlements,
    _key: IdempotencyKey,
) -> ExpenseOut:
    """Change a payment's amount, date or note. The old version stays in history."""
    return expense_out(await settlements.edit_payment(user, expense_id, body))
