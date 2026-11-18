"""Request bodies for /v1/settlements: recording that someone paid someone back
(PRD section 8). The response is the same ExpenseOut as expenses, with kind "settlement"."""

import uuid
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Notes = Annotated[str, StringConstraints(max_length=2000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettlementIn(Strict):
    """ "Aditi paid Ben S$20". Either Aditi or Ben can record it, for any amount."""

    payer_id: uuid.UUID  # who handed over the money
    receiver_id: uuid.UUID  # who got it
    amount_minor: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    expense_date: date
    notes: Notes | None = None
    # Inside a group (both people must be members): how the group screen's "Ben pays
    # Chen" is recorded. Leave out for a payment outside groups.
    group_id: uuid.UUID | None = None


class SettlementEditIn(Strict):
    """Change a recorded payment's amount, date or note. The two people and the currency
    stay the same."""

    amount_minor: int
    expense_date: date
    notes: Notes | None = None
