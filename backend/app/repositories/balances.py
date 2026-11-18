"""Database queries for the materialised balances table (PRD section 8)."""

import uuid
from typing import NamedTuple

from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Balance
from app.models.expense import ContextType


class Key(NamedTuple):
    """Which balance row: the context, the ordered pair (a < b), and the currency."""

    context_type: ContextType
    group_id: uuid.UUID | None
    party_a: uuid.UUID
    party_b: uuid.UUID
    currency: str

    def sort_key(self) -> tuple[str, ...]:
        return (self.context_type, str(self.group_id), str(self.party_a), str(self.party_b),
                self.currency)  # fmt: skip


async def apply(session: AsyncSession, deltas: dict[Key, int]) -> None:
    """Add each delta to its row (creating it if needed), in one statement.

    `amount = amount + delta` is done by the database, so two expenses touching the same
    pair at the same time both count. Rows are written in a fixed order, so two such
    transactions lock rows in the same order and can't deadlock.
    """
    rows = [
        {**key._asdict(), "amount_minor": delta}
        for key, delta in sorted(deltas.items(), key=lambda kv: kv[0].sort_key())
        if delta
    ]
    if not rows:
        return
    stmt = insert(Balance).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_balances_key",
        set_={"amount_minor": Balance.amount_minor + stmt.excluded.amount_minor},
    )
    await session.execute(stmt)


def _key(b: Balance) -> Key:
    return Key(b.context_type, b.group_id, b.party_a, b.party_b, b.currency)


async def for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Balance]:
    """Every non-zero balance this person is part of."""
    stmt = select(Balance).where(
        or_(Balance.party_a == user_id, Balance.party_b == user_id), Balance.amount_minor != 0
    )
    return list((await session.execute(stmt)).scalars())


async def between(session: AsyncSession, x: uuid.UUID, y: uuid.UUID) -> list[Balance]:
    a, b = (x, y) if x < y else (y, x)
    stmt = select(Balance).where(
        and_(Balance.party_a == a, Balance.party_b == b), Balance.amount_minor != 0
    )
    return list((await session.execute(stmt)).scalars())


async def in_group_for(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> list[Balance]:
    stmt = select(Balance).where(
        Balance.group_id == group_id,
        or_(Balance.party_a == user_id, Balance.party_b == user_id),
        Balance.amount_minor != 0,
    )
    return list((await session.execute(stmt)).scalars())


async def all_nonzero(session: AsyncSession) -> dict[Key, int]:
    rows = await session.execute(select(Balance).where(Balance.amount_minor != 0))
    return {_key(b): b.amount_minor for b in rows.scalars()}


async def lock_for_audit(session: AsyncSession) -> None:
    """Pause balance writes until this transaction ends, so the audit compares the table
    with the ledger at one consistent moment. Reads carry on as normal."""
    await session.execute(text("LOCK TABLE balances IN EXCLUSIVE MODE"))
