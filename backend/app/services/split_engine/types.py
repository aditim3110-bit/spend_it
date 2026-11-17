"""The engine's inputs and outputs. Plain frozen dataclasses (no web or database code)
so the Swift port can mirror them one-to-one.

All money is integer minor units (S$84.50 is 8450). IDs are lowercase ASCII strings
(canonical UUIDs in production) and are compared byte by byte for tie-breaks.
"""

from dataclasses import dataclass
from enum import StrEnum


class SplitMode(StrEnum):
    EQUAL = "equal"  # no value per person
    EXACT = "exact"  # value = amount owed, in minor units
    PERCENT = "percent"  # value = basis points (3333 = 33.33%), must total 10000
    SHARES = "shares"  # value = integer weight (a couple sharing a room = 2)


@dataclass(frozen=True, slots=True)
class Payer:
    id: str
    amount: int


@dataclass(frozen=True, slots=True)
class ShareInput:
    id: str
    value: int | None = None  # None only in EQUAL mode


@dataclass(frozen=True, slots=True)
class SplitRequest:
    total: int
    currency: str
    payers: tuple[Payer, ...]
    mode: SplitMode
    inputs: tuple[ShareInput, ...]


@dataclass(frozen=True, slots=True)
class Share:
    id: str
    owed: int
    input_value: int | None  # what the user typed; saved as expense_shares.input_value


@dataclass(frozen=True, slots=True)
class SplitResult:
    total: int
    currency: str
    mode: SplitMode
    payers: tuple[Payer, ...]
    shares: tuple[Share, ...]  # same order as the request's inputs

    def nets(self) -> dict[str, int]:
        """paid - owed per person. Positive: others owe them. Always sums to 0."""
        net: dict[str, int] = {}
        for p in self.payers:
            net[p.id] = net.get(p.id, 0) + p.amount
        for s in self.shares:
            net[s.id] = net.get(s.id, 0) - s.owed
        return net
