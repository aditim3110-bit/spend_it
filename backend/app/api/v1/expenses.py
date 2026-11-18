"""/v1/expenses: direct expenses between friends (PRD sections 7 and 17).

If two people edit at about the same time, the last save wins and nobody has to reload.
The earlier save isn't lost: every version stays in GET /expenses/{id}/revisions.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core import pagination
from app.core.idempotency import idempotency_key_header
from app.db.session import get_session
from app.models import ExpensePayer, ExpenseShare
from app.repositories.expenses import RevisionRows
from app.schemas.expenses import (
    ExpenseIn,
    ExpenseOut,
    ExpensePageOut,
    ExpenseStatus,
    PayerOut,
    RevisionListOut,
    RevisionOut,
    ShareOut,
)
from app.services.expenses import ExpenseService, ExpenseView

router = APIRouter(prefix="/expenses", tags=["expenses"])
IdempotencyKey = Annotated[uuid.UUID, Depends(idempotency_key_header)]


def get_expense_service(session: Annotated[AsyncSession, Depends(get_session)]) -> ExpenseService:
    return ExpenseService(session)


Expenses = Annotated[ExpenseService, Depends(get_expense_service)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ExpenseOut)
async def create_expense(
    body: ExpenseIn, user: CurrentUser, expenses: Expenses, _key: IdempotencyKey
) -> ExpenseOut:
    """Add an expense. Send who paid and how to split; the server works out who owes what."""
    return expense_out(await expenses.create(user, body))


@router.get("", response_model=ExpensePageOut)
async def list_expenses(
    user: CurrentUser,
    expenses: Expenses,
    friend_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    status: ExpenseStatus = "live",
    limit: Annotated[int, Query(ge=1, le=pagination.MAX_LIMIT)] = pagination.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> ExpensePageOut:
    """Expenses you're on, newest date first. `group_id` lists every expense in one of your
    groups instead (the group feed). `friend_id` narrows to those involving one person.
    `status=deleted` lists ones deleted in the last 30 days (still restorable)."""
    page = await expenses.page(
        user, friend_id=friend_id, status=status, limit=limit, cursor=cursor, group_id=group_id
    )
    return ExpensePageOut(items=[expense_out(v) for v in page.items], next_cursor=page.next_cursor)


@router.get("/{expense_id}", response_model=ExpenseOut)
async def get_expense(expense_id: uuid.UUID, user: CurrentUser, expenses: Expenses) -> ExpenseOut:
    return expense_out(await expenses.get(user, expense_id))


@router.put("/{expense_id}", response_model=ExpenseOut)
async def edit_expense(
    expense_id: uuid.UUID,
    body: ExpenseIn,
    user: CurrentUser,
    expenses: Expenses,
    _key: IdempotencyKey,
) -> ExpenseOut:
    """Replace the expense with a new version (the last save wins). The old version is
    kept in the history."""
    return expense_out(await expenses.edit(user, expense_id, body))


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID, user: CurrentUser, expenses: Expenses, _key: IdempotencyKey
) -> Response:
    """Delete (restorable for 30 days)."""
    await expenses.delete(user, expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{expense_id}/restore", response_model=ExpenseOut)
async def restore_expense(
    expense_id: uuid.UUID,
    user: CurrentUser,
    expenses: Expenses,
    _key: IdempotencyKey,
) -> ExpenseOut:
    return expense_out(await expenses.restore(user, expense_id))


@router.get("/{expense_id}/revisions", response_model=RevisionListOut)
async def expense_history(
    expense_id: uuid.UUID, user: CurrentUser, expenses: Expenses
) -> RevisionListOut:
    """Every version, oldest first: who changed what, and when."""
    history = await expenses.history(user, expense_id)
    return RevisionListOut(items=[_revision_out(r, history.names) for r in history.revisions])


# --- Mapping ------------------------------------------------------------------------------


def _payers(rows: list[ExpensePayer], names: dict[uuid.UUID, str | None]) -> list[PayerOut]:
    return [
        PayerOut(user_id=p.user_id, display_name=names.get(p.user_id), amount_minor=p.amount_minor)
        for p in rows
        if p.user_id is not None  # guest rows arrive with guest links
    ]


def _shares(rows: list[ExpenseShare], names: dict[uuid.UUID, str | None]) -> list[ShareOut]:
    return [
        ShareOut(
            user_id=s.user_id,
            display_name=names.get(s.user_id),
            owed_minor=s.owed_minor,
            input_value=s.input_value,
        )
        for s in rows
        if s.user_id is not None
    ]


def _revision_out(rows: RevisionRows, names: dict[uuid.UUID, str | None]) -> RevisionOut:
    r = rows.revision
    return RevisionOut(
        rev_no=r.rev_no,
        reason=r.reason,
        name=r.name,
        amount_minor=r.amount_minor,
        currency=r.currency,
        expense_date=r.expense_date,
        split_mode=r.split_mode,
        notes=r.notes,
        payers=_payers(rows.payers, names),
        shares=_shares(rows.shares, names),
        created_by=r.created_by,
        created_at=r.created_at,
    )


def expense_out(view: ExpenseView) -> ExpenseOut:
    e, r = view.expense, view.current.revision
    return ExpenseOut(
        id=e.id,
        kind=e.kind,
        context_type=e.context_type,
        group_id=e.group_id,
        rev_no=r.rev_no,
        name=r.name,
        amount_minor=r.amount_minor,
        currency=r.currency,
        expense_date=r.expense_date,
        split_mode=r.split_mode,
        notes=r.notes,
        payers=_payers(view.current.payers, view.names),
        shares=_shares(view.current.shares, view.names),
        created_by=e.created_by,
        created_at=e.created_at,
        updated_by=r.created_by,
        updated_at=r.created_at,
        deleted_at=e.deleted_at,
        deleted_by=e.deleted_by,
    )
