"""Typed split errors. `code` strings are a contract: the API returns them, the iOS app
shows a message for each, and fixtures/split/*.json assert on them. Never rename one.

`remainder` is always target minus actual: positive = short, negative = over.
"""

from typing import ClassVar, Literal

Side = Literal["payers", "shares"]


class SplitError(Exception):
    code: ClassVar[str] = "SplitError"

    def __init__(
        self,
        message: str,
        *,
        side: Side | None = None,
        participant_id: str | None = None,
        remainder: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.side = side
        self.participant_id = participant_id
        self.remainder = remainder


class UnsupportedCurrency(SplitError):
    code = "UnsupportedCurrency"


class InvalidTotal(SplitError):
    """Total is zero, negative, or above MAX_TOTAL."""

    code = "InvalidTotal"


class EmptyParticipants(SplitError):
    """Nobody paid (side=payers) or nobody is splitting (side=shares)."""

    code = "EmptyParticipants"


class TooManyParticipants(SplitError):
    code = "TooManyParticipants"


class DuplicateParticipant(SplitError):
    code = "DuplicateParticipant"


class InvalidPayerAmount(SplitError):
    """A payer amount is zero, negative, or larger than the total."""

    code = "InvalidPayerAmount"


class SumMismatch(SplitError):
    """Payers (side=payers) or exact amounts (side=shares) don't add up to the total."""

    code = "SumMismatch"


class NegativeShare(SplitError):
    code = "NegativeShare"


class ShareTooLarge(SplitError):
    """An input above its cap: exact > total, percent > 100%, or shares > 1000."""

    code = "ShareTooLarge"


class PercentSumInvalid(SplitError):
    """Percentages don't add up to exactly 100.00%. remainder is in basis points."""

    code = "PercentSumInvalid"


class ZeroTotalWeight(SplitError):
    """Shares mode where every weight is 0, so there is nothing to divide by."""

    code = "ZeroTotalWeight"
