"""Property tests: rules that must hold for *every* valid split, checked on thousands of
random ones. Example tests prove the cases we thought of; these find the ones we didn't.
"""

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.split_engine import (
    Payer,
    ShareInput,
    SplitError,
    SplitMode,
    SplitRequest,
    compute_split,
)
from app.services.split_engine.limits import MAX_SHARE_WEIGHT
from tests.split.strategies import split_requests


def _weights(req: SplitRequest) -> list[int]:
    return [1 if i.value is None else i.value for i in req.inputs]


@settings(max_examples=500)
@given(split_requests())
def test_every_expense_balances(req: SplitRequest) -> None:
    """CLAUDE.md rule 3: paid total == owed total == expense total; nets sum to zero."""
    result = compute_split(req)
    assert sum(s.owed for s in result.shares) == req.total
    assert sum(p.amount for p in result.payers) == req.total
    assert sum(result.nets().values()) == 0
    assert all(s.owed >= 0 for s in result.shares)
    assert [s.id for s in result.shares] == [i.id for i in req.inputs]


@settings(max_examples=500)
@given(
    split_requests(SplitMode.EQUAL)
    | split_requests(SplitMode.PERCENT)
    | split_requests(SplitMode.SHARES)
)
def test_nobody_is_off_by_more_than_one_unit(req: SplitRequest) -> None:
    """Each share is the exact proportional amount rounded down or up, never further."""
    result = compute_split(req)
    weights = _weights(req)
    weight_sum = sum(weights)
    for share, w in zip(result.shares, weights, strict=True):
        exact_times_w = req.total * w  # exact share = this / weight_sum
        assert share.owed * weight_sum <= exact_times_w + weight_sum - 1  # owed <= ceil
        assert share.owed * weight_sum >= exact_times_w - weight_sum + 1  # owed >= floor


@given(split_requests(), st.randoms(use_true_random=False))
def test_input_order_does_not_change_who_owes_what(req: SplitRequest, rng) -> None:
    inputs = list(req.inputs)
    payers = list(req.payers)
    rng.shuffle(inputs)
    rng.shuffle(payers)
    shuffled = replace(req, inputs=tuple(inputs), payers=tuple(payers))
    a = {s.id: s.owed for s in compute_split(req).shares}
    b = {s.id: s.owed for s in compute_split(shuffled).shares}
    assert a == b


@given(split_requests(SplitMode.SHARES), st.integers(2, 10))
def test_scaling_all_shares_changes_nothing(req: SplitRequest, k: int) -> None:
    """2:1:1 and 4:2:2 are the same split."""
    if max(_weights(req)) * k > MAX_SHARE_WEIGHT:
        return
    scaled = replace(req, inputs=tuple(ShareInput(i.id, i.value * k) for i in req.inputs))  # type: ignore[operator]
    assert compute_split(req).shares == tuple(
        replace(s, input_value=s.input_value // k)  # type: ignore[operator]
        for s in compute_split(scaled).shares
    )


@given(split_requests(SplitMode.EQUAL))
def test_single_payer_absorbs_the_rounding_cent(req: SplitRequest) -> None:
    """Your decision (PRD section 7): in an equal split, a sole payer who is splitting
    gets the first leftover cent."""
    payer = req.payers[0].id
    n = len(req.inputs)
    if len(req.payers) != 1 or payer not in {i.id for i in req.inputs} or req.total % n == 0:
        return
    owed = {s.id: s.owed for s in compute_split(req).shares}
    assert owed[payer] == req.total // n + 1


@given(split_requests(SplitMode.EQUAL))
def test_equal_split_differs_by_at_most_one_cent(req: SplitRequest) -> None:
    owed = [s.owed for s in compute_split(req).shares]
    assert max(owed) - min(owed) <= 1


# Fuzzing: throw nonsense at the engine. It must either succeed with a balanced result
# or raise a typed SplitError. Never crash with any other exception.
any_int = st.integers(-(2**63), 2**63 - 1) | st.integers(-5, 20_000)
small_ids = st.sampled_from(["aditi", "ben", "chen", "dev"])


@settings(max_examples=1000)
@given(
    total=any_int,
    currency=st.sampled_from(["SGD", "JPY", "KWD", "XYZ", "XAU", "sgd", ""]),
    payers=st.lists(st.builds(Payer, small_ids, any_int), max_size=5),
    mode=st.sampled_from(list(SplitMode)),
    values=st.lists(st.tuples(small_ids, any_int), max_size=6),
)
def test_nonsense_input_gives_typed_error_or_balanced_result(
    total: int,
    currency: str,
    payers: list[Payer],
    mode: SplitMode,
    values: list[tuple[str, int]],
) -> None:
    inputs = tuple(ShareInput(pid, None if mode is SplitMode.EQUAL else v) for pid, v in values)
    req = SplitRequest(total, currency, tuple(payers), mode, inputs)
    try:
        result = compute_split(req)
    except SplitError:
        return
    assert sum(s.owed for s in result.shares) == total
