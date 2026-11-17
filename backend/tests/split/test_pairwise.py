"""Who owes whom within one expense (app/services/split_engine/pairwise.py)."""

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.split_engine import compute_split, pairwise_debts
from tests.split.strategies import split_requests

# --- Examples -----------------------------------------------------------------------------


def test_hotel_two_payers_only_the_short_person_pays() -> None:
    """S$300 hotel, three ways. Aditi paid 200, Ben 100: Chen owes Aditi 100, Ben square."""
    nets = {"aditi": 20000 - 10000, "ben": 10000 - 10000, "chen": -10000}
    assert pairwise_debts(nets) == {("chen", "aditi"): 10000}


def test_one_payer_everyone_owes_their_share() -> None:
    # S$100 three ways, Aditi paid: 3334 / 3333 / 3333.
    nets = {"aditi": 10000 - 3334, "ben": -3333, "chen": -3333}
    assert pairwise_debts(nets) == {("ben", "aditi"): 3333, ("chen", "aditi"): 3333}


def test_two_short_two_out_of_pocket_with_odd_cents() -> None:
    # a is owed 2, b is owed 1; c owes 2, d owes 1.
    # c goes first (ID order): 2 split 2:1 over a and b is 1.33 / 0.67, so a gets 1 and
    # b gets 0, with 1 cent left. b's remainder (.67) beats a's (.33), so b gets it.
    # Then a is still owed 1, which d pays.
    nets = {"a": 2, "b": 1, "c": -2, "d": -1}
    debts = pairwise_debts(nets)
    assert debts == {("c", "a"): 1, ("c", "b"): 1, ("d", "a"): 1}
    _check_conserves(nets, debts)


def test_everyone_square_means_no_debts() -> None:
    assert pairwise_debts({"a": 0, "b": 0}) == {}
    assert pairwise_debts({}) == {}


def test_unbalanced_nets_are_a_bug() -> None:
    with pytest.raises(ValueError, match="sum to zero"):
        pairwise_debts({"a": 5, "b": -4})


# --- Properties ---------------------------------------------------------------------------


def _check_conserves(nets: dict[str, int], debts: dict[tuple[str, str], int]) -> None:
    received = dict.fromkeys(nets, 0)
    for (debtor, creditor), amount in debts.items():
        assert amount > 0
        assert nets[debtor] < 0 < nets[creditor]  # only short -> out of pocket
        received[creditor] += amount
        received[debtor] -= amount
    assert received == nets  # everyone ends exactly at their net


nets_strategy = st.lists(st.integers(-(10**13), 10**13), min_size=1, max_size=30).map(
    lambda xs: {f"p{i:02d}": x for i, x in enumerate([*xs, -sum(xs)])}
)


@settings(max_examples=500)
@given(nets_strategy)
def test_every_person_ends_exactly_at_their_net(nets: dict[str, int]) -> None:
    _check_conserves(nets, pairwise_debts(nets))


@settings(max_examples=300)
@given(nets_strategy, st.randoms(use_true_random=False))
def test_input_order_does_not_matter(nets: dict[str, int], rnd: random.Random) -> None:
    items = list(nets.items())
    rnd.shuffle(items)
    assert pairwise_debts(dict(items)) == pairwise_debts(nets)


@settings(max_examples=300)
@given(split_requests())
def test_one_payer_owes_exactly_the_shares(req) -> None:
    result = compute_split(req)
    debts = pairwise_debts(result.nets())
    _check_conserves(result.nets(), debts)
    if len(req.payers) == 1:
        payer = req.payers[0].id
        expected = {(s.id, payer): s.owed for s in result.shares if s.id != payer and s.owed}
        assert debts == expected
