"""Request and response bodies for /v1/expenses (PRD sections 7 and 17).

The client sends what the person typed: who paid how much, the split mode and each
person's input. It never sends who owes what; the server works that out with the split
engine and saves its own result (CLAUDE.md rule 6). Extra fields are rejected, so a client
can't slip in its own computed shares.

People are referenced as {"user_id": ...}. Guests will be added later as {"guest_id": ...}
without changing this shape.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.expense import (
    ContextType,
    ExpenseKind,
    RevisionReason,
    SplitModeDb,
)
from app.services.split_engine import SplitMode
from app.services.split_engine.limits import MAX_PARTICIPANTS, MAX_PAYERS

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Notes = Annotated[str, StringConstraints(max_length=2000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- In -----------------------------------------------------------------------------------


class PayerIn(Strict):
    user_id: uuid.UUID
    amount_minor: int


class ShareIn(Strict):
    user_id: uuid.UUID
    # Exact: minor units. Percent: basis points (3333 = 33.33%). Shares: weight. Equal: omit.
    value: int | None = None


class SplitIn(Strict):
    mode: SplitMode
    # One more than the cap is allowed through, so the engine reports TooManyParticipants
    # with its usual error instead of a generic validation error.
    shares: list[ShareIn] = Field(max_length=MAX_PARTICIPANTS + 1)


class ExpenseIn(Strict):
    name: Name
    amount_minor: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    expense_date: date
    notes: Notes | None = None
    payers: list[PayerIn] = Field(max_length=MAX_PAYERS + 1)
    split: SplitIn
    # Set for a group expense (PRD section 9); leave out for a direct one between friends.
    # An existing expense keeps its group: moving it is a separate action.
    group_id: uuid.UUID | None = None


# --- Out ----------------------------------------------------------------------------------


class PayerOut(Strict):
    user_id: uuid.UUID
    display_name: str | None
    amount_minor: int


class ShareOut(Strict):
    user_id: uuid.UUID
    display_name: str | None
    owed_minor: int
    input_value: int | None


class RevisionOut(Strict):
    """One version of the expense, as it was saved."""

    rev_no: int
    reason: RevisionReason
    name: str
    amount_minor: int
    currency: str
    expense_date: date
    split_mode: SplitModeDb
    notes: str | None
    payers: list[PayerOut]
    shares: list[ShareOut]
    created_by: uuid.UUID
    created_at: datetime


class ExpenseOut(Strict):
    """The current version. `rev_no` counts the versions (1 = never edited).

    kind "settlement" is a recorded payment: the one payer handed money to the one person
    in `shares`. Payments show in the feed alongside expenses."""

    id: uuid.UUID
    kind: ExpenseKind
    context_type: ContextType
    group_id: uuid.UUID | None
    rev_no: int
    name: str
    amount_minor: int
    currency: str
    expense_date: date
    split_mode: SplitModeDb
    notes: str | None
    payers: list[PayerOut]
    shares: list[ShareOut]
    created_by: uuid.UUID
    created_at: datetime
    updated_by: uuid.UUID
    updated_at: datetime
    deleted_at: datetime | None
    deleted_by: uuid.UUID | None


class ExpensePageOut(Strict):
    items: list[ExpenseOut]
    next_cursor: str | None


class RevisionListOut(Strict):
    items: list[RevisionOut]


ExpenseStatus = Literal["live", "deleted"]
