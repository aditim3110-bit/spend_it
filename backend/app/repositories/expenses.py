"""Database queries for expenses and their revisions (PRD sections 7 and 16).

Only inserts touch the revision, payer and share tables: the database refuses updates
and deletes there. The `expenses` row is the one mutable thing: it points at the current
revision and holds the soft-delete fields.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import exists, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Expense, ExpensePayer, ExpenseRevision, ExpenseShare
from app.models.expense import (
    ContextType,
    ExpenseKind,
    RevisionReason,
    SplitModeDb,
)


@dataclass(frozen=True, slots=True)
class RevisionData:
    """Everything one revision stores. Shares are (user, owed, input_value) as the split
    engine computed them."""

    name: str
    amount_minor: int
    currency: str
    expense_date: date
    split_mode: SplitModeDb
    notes: str | None
    payers: list[tuple[uuid.UUID, int]]
    shares: list[tuple[uuid.UUID, int, int | None]]

    def people(self) -> set[uuid.UUID]:
        return {p for p, _ in self.payers} | {s for s, _, _ in self.shares}


@dataclass(frozen=True, slots=True)
class RevisionRows:
    revision: ExpenseRevision
    payers: list[ExpensePayer]
    shares: list[ExpenseShare]

    def people(self) -> set[uuid.UUID]:
        return {p.user_id for p in self.payers if p.user_id} | {
            s.user_id for s in self.shares if s.user_id
        }


# --- Writes -------------------------------------------------------------------------------


async def create(
    session: AsyncSession,
    user_id: uuid.UUID,
    data: RevisionData,
    kind: ExpenseKind = ExpenseKind.EXPENSE,
) -> Expense:
    """A new direct expense (or settlement) with revision 1. The caller commits."""
    expense = Expense(
        id=uuid.uuid4(),
        kind=kind,
        context_type=ContextType.DIRECT,
        group_id=None,
        expense_date=data.expense_date,
        created_by=user_id,
    )
    session.add(expense)
    # The expense must exist before its first revision can point at it; the expense then
    # points back at the revision (the two tables reference each other).
    await session.flush()
    await add_revision(session, expense, user_id, 1, RevisionReason.CREATE, data)
    return expense


async def add_revision(
    session: AsyncSession,
    expense: Expense,
    user_id: uuid.UUID,
    rev_no: int,
    reason: RevisionReason,
    data: RevisionData,
) -> ExpenseRevision:
    """Append a revision and make it the current one. The caller commits."""
    revision = ExpenseRevision(
        id=uuid.uuid4(),
        expense_id=expense.id,
        rev_no=rev_no,
        context_type=expense.context_type,
        group_id=expense.group_id,
        name=data.name,
        amount_minor=data.amount_minor,
        currency=data.currency,
        expense_date=data.expense_date,
        split_mode=data.split_mode,
        notes=data.notes,
        reason=reason,
        created_by=user_id,
    )
    session.add(revision)
    # Save the revision before its rows: the models don't declare relationships, so
    # SQLAlchemy can't work out that order by itself.
    await session.flush()
    session.add_all(
        ExpensePayer(revision_id=revision.id, user_id=uid, amount_minor=amount)
        for uid, amount in data.payers
    )
    session.add_all(
        ExpenseShare(revision_id=revision.id, user_id=uid, owed_minor=owed, input_value=value)
        for uid, owed, value in data.shares
    )
    await session.flush()
    expense.current_revision_id = revision.id
    expense.expense_date = data.expense_date
    await session.flush()
    return revision


async def set_deleted(
    session: AsyncSession, expense: Expense, at: datetime | None, by: uuid.UUID | None
) -> None:
    expense.deleted_at = at
    expense.deleted_by = by
    await session.flush()


# --- Reads --------------------------------------------------------------------------------


async def get(
    session: AsyncSession, expense_id: uuid.UUID, *, lock: bool = False
) -> Expense | None:
    """`lock=True` takes a row lock until commit, so two edits of the same expense queue
    up one after the other instead of both building on the same old version."""
    stmt = select(Expense).where(Expense.id == expense_id).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def load_revisions(
    session: AsyncSession, revision_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RevisionRows]:
    """Revisions with their payer and share rows, in three queries however many there are."""
    if not revision_ids:
        return {}
    revisions = (
        await session.execute(
            select(ExpenseRevision)
            .where(ExpenseRevision.id.in_(revision_ids))
            .execution_options(populate_existing=True)
        )
    ).scalars()
    payers = (
        await session.execute(
            select(ExpensePayer).where(ExpensePayer.revision_id.in_(revision_ids))
        )
    ).scalars()
    shares = (
        await session.execute(
            select(ExpenseShare).where(ExpenseShare.revision_id.in_(revision_ids))
        )
    ).scalars()
    by_rev_payers: dict[uuid.UUID, list[ExpensePayer]] = {}
    for p in payers:
        by_rev_payers.setdefault(p.revision_id, []).append(p)
    by_rev_shares: dict[uuid.UUID, list[ExpenseShare]] = {}
    for s in shares:
        by_rev_shares.setdefault(s.revision_id, []).append(s)

    def by_person(row: ExpensePayer | ExpenseShare) -> str:
        return str(row.user_id or row.guest_id)  # stable order in responses

    return {
        r.id: RevisionRows(
            revision=r,
            payers=sorted(by_rev_payers.get(r.id, []), key=by_person),
            shares=sorted(by_rev_shares.get(r.id, []), key=by_person),
        )
        for r in revisions
    }


async def revision_ids(session: AsyncSession, expense_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = (
        select(ExpenseRevision.id)
        .where(ExpenseRevision.expense_id == expense_id)
        .order_by(ExpenseRevision.rev_no)
    )
    return list((await session.execute(stmt)).scalars())


async def ever_involved(session: AsyncSession, expense_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Was this person in any version of the expense (paid or owed)?"""
    in_revision = ExpenseRevision.expense_id == expense_id
    payer = (
        select(ExpensePayer.id)
        .join(ExpenseRevision, ExpenseRevision.id == ExpensePayer.revision_id)
        .where(in_revision, ExpensePayer.user_id == user_id)
    )
    share = (
        select(ExpenseShare.id)
        .join(ExpenseRevision, ExpenseRevision.id == ExpenseShare.revision_id)
        .where(in_revision, ExpenseShare.user_id == user_id)
    )
    stmt = select(or_(exists(payer), exists(share)))
    return bool((await session.execute(stmt)).scalar())


def _in_current(user_id: uuid.UUID):
    """SQL: this person is in the expense's current version."""
    return or_(
        exists().where(
            ExpenseShare.revision_id == Expense.current_revision_id,
            ExpenseShare.user_id == user_id,
        ),
        exists().where(
            ExpensePayer.revision_id == Expense.current_revision_id,
            ExpensePayer.user_id == user_id,
        ),
    )


async def feed(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    friend_id: uuid.UUID | None,
    deleted_since: datetime | None,
    limit: int,
    after: tuple[date, datetime, uuid.UUID] | None,
) -> list[Expense]:
    """Expenses the user is in, newest expense date first.

    `deleted_since=None` lists live expenses; otherwise expenses deleted since then (the
    ones that can still be restored). `after` is the sort key of the previous page's last
    item.
    """
    stmt = select(Expense).where(_in_current(user_id)).execution_options(populate_existing=True)
    if friend_id is not None:
        stmt = stmt.where(_in_current(friend_id))
    if deleted_since is None:
        stmt = stmt.where(Expense.deleted_at.is_(None))
    else:
        stmt = stmt.where(Expense.deleted_at >= deleted_since)
    key = tuple_(Expense.expense_date, Expense.created_at, Expense.id)
    if after is not None:
        stmt = stmt.where(key < tuple_(*after))
    stmt = stmt.order_by(
        Expense.expense_date.desc(), Expense.created_at.desc(), Expense.id.desc()
    ).limit(limit)
    return list((await session.execute(stmt)).scalars())
