"""compute_split: the one place that validates a split and does the rounding.

Checks run in a fixed order (documented in fixtures/split/README.md) so that Python
and Swift report the same error when an input has more than one problem.
"""

from collections.abc import Sequence

from app.services.split_engine import currency
from app.services.split_engine.allocate import largest_remainder
from app.services.split_engine.errors import (
    DuplicateParticipant,
    EmptyParticipants,
    InvalidPayerAmount,
    InvalidTotal,
    NegativeShare,
    PercentSumInvalid,
    ShareTooLarge,
    Side,
    SumMismatch,
    TooManyParticipants,
    UnsupportedCurrency,
    ZeroTotalWeight,
)
from app.services.split_engine.limits import (
    MAX_PARTICIPANTS,
    MAX_PAYERS,
    MAX_SHARE_WEIGHT,
    MAX_TOTAL,
    PERCENT_TOTAL,
)
from app.services.split_engine.types import Share, SplitMode, SplitRequest, SplitResult


def compute_split(req: SplitRequest) -> SplitResult:
    """Validate `req` and return who owes what. Raises a SplitError subclass if invalid."""
    total, payers, inputs, mode = req.total, req.payers, req.inputs, req.mode

    # 1-2. Currency and total.
    if not currency.is_supported(req.currency):
        raise UnsupportedCurrency(f"{req.currency!r} is not a supported currency.")
    if not 0 < total <= MAX_TOTAL:
        raise InvalidTotal(f"Total must be between 1 and {MAX_TOTAL} minor units.")

    # 3. Somebody paid, somebody is splitting.
    if not payers:
        raise EmptyParticipants("Nobody paid.", side="payers")
    if not inputs:
        raise EmptyParticipants("Nobody is splitting the expense.", side="shares")

    # 4. Not too many people.
    if len(payers) > MAX_PAYERS:
        raise TooManyParticipants(f"At most {MAX_PAYERS} payers.", side="payers")
    if len(inputs) > MAX_PARTICIPANTS:
        raise TooManyParticipants(f"At most {MAX_PARTICIPANTS} participants.", side="shares")

    # 5. Nobody listed twice.
    _reject_duplicates([p.id for p in payers], "payers")
    _reject_duplicates([i.id for i in inputs], "shares")

    # 6-7. Each payer paid a sensible amount, and together they paid the total.
    for p in payers:
        if not 0 < p.amount <= total:
            raise InvalidPayerAmount(
                f"Payer {p.id} must have paid between 1 and the total.", participant_id=p.id
            )
    paid = sum(p.amount for p in payers)
    if paid != total:
        raise SumMismatch(
            "Payers don't add up to the total.", side="payers", remainder=total - paid
        )

    # 8-10. The split itself.
    if mode is SplitMode.EQUAL:
        owed = largest_remainder(total, [(i.id, 1) for i in inputs], _single_payer(req))
        return _result(req, owed, with_values=False)

    values = [(i.id, _value(i.id, i.value, mode)) for i in inputs]
    for pid, v in values:
        if v < 0:
            raise NegativeShare(f"{pid} has a negative amount.", side="shares", participant_id=pid)
    cap = {SplitMode.EXACT: total, SplitMode.PERCENT: PERCENT_TOTAL}.get(mode, MAX_SHARE_WEIGHT)
    for pid, v in values:
        if v > cap:
            raise ShareTooLarge(
                f"{pid}'s value is above the maximum of {cap}.", side="shares", participant_id=pid
            )
    value_sum = sum(v for _, v in values)

    if mode is SplitMode.EXACT:
        if value_sum != total:
            raise SumMismatch(
                "Amounts don't add up to the total.", side="shares", remainder=total - value_sum
            )
        return _result(req, dict(values), with_values=True)

    if mode is SplitMode.PERCENT and value_sum != PERCENT_TOTAL:
        raise PercentSumInvalid(
            "Percentages must add up to exactly 100%.", remainder=PERCENT_TOTAL - value_sum
        )
    if mode is SplitMode.SHARES and value_sum == 0:
        raise ZeroTotalWeight("At least one person needs more than 0 shares.")

    owed = largest_remainder(total, values, _single_payer(req))
    return _result(req, owed, with_values=True)


def _reject_duplicates(ids: Sequence[str], side: Side) -> None:
    seen: set[str] = set()
    for pid in ids:
        if pid in seen:
            raise DuplicateParticipant(f"{pid} is listed twice.", side=side, participant_id=pid)
        seen.add(pid)


def _single_payer(req: SplitRequest) -> str | None:
    """The tie-break priority: the payer, but only when there is exactly one."""
    return req.payers[0].id if len(req.payers) == 1 else None


def _value(pid: str, value: int | None, mode: SplitMode) -> int:
    # A missing value is a programming error, not a user error: the API's request
    # schema guarantees a value for exact/percent/shares before we get here.
    if value is None:
        raise ValueError(f"{mode} mode needs a value for {pid}")
    return value


def _result(req: SplitRequest, owed: dict[str, int], *, with_values: bool) -> SplitResult:
    shares = tuple(
        Share(id=i.id, owed=owed[i.id], input_value=i.value if with_values else None)
        for i in req.inputs
    )
    return SplitResult(
        total=req.total, currency=req.currency, mode=req.mode, payers=req.payers, shares=shares
    )
