"""Response bodies for /v1/balances (PRD section 8).

Amounts are integer minor units, always per currency (never added across currencies).
A positive amount means the other person owes you; negative means you owe them.
"""

import uuid

from pydantic import BaseModel, ConfigDict

from app.models.expense import ContextType


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AmountOut(Strict):
    currency: str
    amount_minor: int  # positive: they owe you; negative: you owe them


class CurrencyTotalOut(Strict):
    currency: str
    owed_to_you: int  # >= 0
    you_owe: int  # >= 0


class PersonBalanceOut(Strict):
    user_id: uuid.UUID
    display_name: str | None
    amounts: list[AmountOut]


class BalancesOut(Strict):
    """The home screen: totals per currency, then one line per person."""

    totals: list[CurrencyTotalOut]
    people: list[PersonBalanceOut]


class ContextBalanceOut(Strict):
    context_type: ContextType
    group_id: uuid.UUID | None
    amounts: list[AmountOut]


class PersonDetailOut(PersonBalanceOut):
    """One person: the overall amounts, and where they come from (direct, or per group)."""

    contexts: list[ContextBalanceOut]
