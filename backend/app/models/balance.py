"""Materialised balances: who owes whom, per currency, per context (PRD sections 8, 16).

One row per pair of people per currency per context, smaller user ID first (party_a).
amount_minor > 0 means party_b owes party_a; < 0 means party_a owes party_b.

This table is a *cache* of the ledger: it is updated in the same transaction as every
expense write, and the nightly audit (app/jobs/audit.py) rebuilds it from the revisions
and repairs any difference. The revisions are the truth.
"""

import uuid

from sqlalchemy import CHAR, BigInteger, CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import CURRENCY_CHECK, Base, IdMixin, text_enum
from app.models.expense import CONTEXT_CHECK, ContextType


class Balance(IdMixin, Base):
    __tablename__ = "balances"

    context_type: Mapped[ContextType] = mapped_column(
        text_enum(ContextType, "balance_context_type")
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id"))
    party_a: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    party_b: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(CHAR(3))
    amount_minor: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint("party_a < party_b", name="ordered_pair"),
        CheckConstraint(CONTEXT_CHECK, name="context_matches_group"),
        CheckConstraint(f"currency {CURRENCY_CHECK}", name="currency_format"),
        # One row per pair, currency and context. NULLS NOT DISTINCT makes "no group"
        # (direct) count as one value, so direct balances can't be duplicated either.
        UniqueConstraint(
            "context_type",
            "group_id",
            "party_a",
            "party_b",
            "currency",
            name="uq_balances_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
