"""The ledger (PRD sections 7, 10 and 16).

An expense is a pointer to its *current* revision. Every edit or move adds a new
revision; old revisions, and their payer and share rows, can never be changed.
The migration installs a database trigger that blocks UPDATE and DELETE on those three
tables, so even a bug can't rewrite history.

Each revision is self-contained: payers and shares each add up to amount_minor. The split
engine guarantees this when the service layer writes, and the nightly audit re-checks it.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    CURRENCY_CHECK,
    MAX_TOTAL,
    Base,
    CreatedAtMixin,
    IdMixin,
    exactly_one,
    text_enum,
)


class ContextType(StrEnum):
    DIRECT = "direct"  # between the people involved, no group
    GROUP = "group"


class ExpenseKind(StrEnum):
    EXPENSE = "expense"
    SETTLEMENT = "settlement"  # "Ben paid Aditi back S$20" uses the same payer/share rows


class SplitModeDb(StrEnum):
    EQUAL = "equal"
    EXACT = "exact"
    PERCENT = "percent"
    SHARES = "shares"
    ITEMS = "items"  # from receipt claims, Phase 2 (PRD section 14)


class RevisionReason(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    MOVE = "move"


CONTEXT_CHECK = "(context_type = 'group') = (group_id IS NOT NULL)"


class Expense(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "expenses"

    kind: Mapped[ExpenseKind] = mapped_column(text_enum(ExpenseKind, "expense_kind"))
    # context_type, group_id and expense_date mirror the current revision, so feeds and
    # balances can filter without joining every revision.
    context_type: Mapped[ContextType] = mapped_column(text_enum(ContextType, "context_type"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id"))
    expense_date: Mapped[date] = mapped_column(Date)
    # Nullable only for the instant between inserting the expense and its first revision
    # (the two tables point at each other), inside one transaction.
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(CONTEXT_CHECK, name="context_matches_group"),
        # The current revision must be one of THIS expense's revisions. The FK is added
        # after expense_revisions exists, because the two tables point at each other.
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            ["expense_revisions.id", "expense_revisions.expense_id"],
            name="fk_expenses_current_revision",
            use_alter=True,
        ),
        # Group feed, newest first, live expenses only (PRD section 16 indexing priorities).
        Index(
            "ix_expenses_group_feed",
            "group_id",
            text("expense_date DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ExpenseRevision(IdMixin, CreatedAtMixin, Base):
    """One immutable version of an expense."""

    __tablename__ = "expense_revisions"

    expense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expenses.id"), index=True)
    rev_no: Mapped[int] = mapped_column(Integer)  # 1, 2, 3...
    context_type: Mapped[ContextType] = mapped_column(
        text_enum(ContextType, "revision_context_type")
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id"))
    name: Mapped[str] = mapped_column(String(120))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3))
    expense_date: Mapped[date] = mapped_column(Date)
    split_mode: Mapped[SplitModeDb] = mapped_column(text_enum(SplitModeDb, "split_mode"))
    notes: Mapped[str | None] = mapped_column(Text)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # FK added with receipts table
    reason: Mapped[RevisionReason] = mapped_column(text_enum(RevisionReason, "revision_reason"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        UniqueConstraint("expense_id", "rev_no"),
        UniqueConstraint("id", "expense_id"),  # target of expenses.fk_expenses_current_revision
        CheckConstraint("rev_no >= 1", name="rev_no_positive"),
        CheckConstraint(CONTEXT_CHECK, name="context_matches_group"),
        CheckConstraint(f"amount_minor > 0 AND amount_minor <= {MAX_TOTAL}", name="amount_range"),
        CheckConstraint(f"currency {CURRENCY_CHECK}", name="currency_format"),
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("char_length(notes) <= 2000", name="notes_length"),
    )


class ExpensePayer(IdMixin, Base):
    """Who paid how much in one revision. Sum of amount_minor = revision.amount_minor."""

    __tablename__ = "expense_payers"

    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_revisions.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guest_identities.id"), index=True
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(exactly_one("user_id", "guest_id"), name="user_xor_guest"),
        CheckConstraint(f"amount_minor > 0 AND amount_minor <= {MAX_TOTAL}", name="amount_range"),
        UniqueConstraint("revision_id", "user_id"),
        UniqueConstraint("revision_id", "guest_id"),
    )


class ExpenseShare(IdMixin, Base):
    """Who owes how much in one revision. Sum of owed_minor = revision.amount_minor.

    A person who owes 0 still gets a row (decided in Phase 0), so they show on the expense.
    input_value is what was typed: minor units (exact), basis points (percent), weight
    (shares), or NULL (equal).
    """

    __tablename__ = "expense_shares"

    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_revisions.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guest_identities.id"), index=True
    )
    owed_minor: Mapped[int] = mapped_column(BigInteger)
    input_value: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(exactly_one("user_id", "guest_id"), name="user_xor_guest"),
        CheckConstraint(f"owed_minor >= 0 AND owed_minor <= {MAX_TOTAL}", name="owed_range"),
        CheckConstraint("input_value IS NULL OR input_value >= 0", name="input_value_non_negative"),
        UniqueConstraint("revision_id", "user_id"),
        UniqueConstraint("revision_id", "guest_id"),
    )
