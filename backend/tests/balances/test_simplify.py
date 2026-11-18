"""Smart Settle (app/services/simplify.py)."""

from collections import defaultdict
from itertools import combinations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.simplify import simplify


def everyone(a: str, b: str) -> bool:
    return True


def nets_of(debts: dict[tuple[str, str], int]) -> dict[str, int]:
    nets: dict[str, int] = defaultdict(int)
    for (debtor, creditor), amount in debts.items():
        nets[debtor] -= amount
        nets[creditor] += amount
    return {p: n for p, n in nets.items() if n}


# --- Examples -----------------------------------------------------------------------------


def test_chain_becomes_one_payment() -> None:
    """Aditi owes Ben 10, Ben owes Chen 10: Aditi pays Chen 10."""
    plain = {("aditi", "ben"): 1000, ("ben", "chen"): 1000}
    assert simplify(nets_of(plain), plain, everyone) == {("aditi", "chen"): 1000}


def test_circle_cancels_out() -> None:
    plain = {("a", "b"): 500, ("b", "c"): 500, ("c", "a"): 500}
    assert simplify(nets_of(plain), plain, everyone) == {}


def test_biggest_debtor_pays_biggest_creditor() -> None:
    nets = {"a": -700, "b": -300, "c": 600, "d": 400}
    plain = {("a", "c"): 600, ("a", "d"): 100, ("b", "d"): 300}
    assert simplify(nets, plain, everyone) == {
        ("a", "c"): 600,
        ("a", "d"): 100,
        ("b", "d"): 300,
    }


def test_never_pay_someone_who_is_not_a_friend() -> None:
    """Aditi removed Chen as a friend: she keeps paying Ben, who pays Chen."""
    plain = {("aditi", "ben"): 1000, ("ben", "chen"): 1000}

    def friends(a: str, b: str) -> bool:
        return {a, b} != {"aditi", "chen"}

    assert simplify(nets_of(plain), plain, friends) == plain


def test_detour_through_a_friend() -> None:
    """A owes B, B owes C, C owes D; A and D aren't friends. The chain gets shorter
    (fewer payments), positions don't change, and A is never told to pay D."""
    plain = {("a", "b"): 10, ("b", "c"): 10, ("c", "d"): 10}

    def friends(x: str, y: str) -> bool:
        return {x, y} != {"a", "d"}

    result = simplify(nets_of(plain), plain, friends)
    assert nets_of(result) == {"a": -10, "d": 10}
    assert all(friends(x, y) or (x, y) in plain for (x, y) in result)
    assert len(result) < len(plain)


def test_unbalanced_input_is_a_bug() -> None:
    with pytest.raises(ValueError, match="sum to zero"):
        simplify({"a": 5}, {}, everyone)


# --- Properties ---------------------------------------------------------------------------

people = [f"p{i}" for i in range(6)]
plain_debts = st.dictionaries(
    st.tuples(st.sampled_from(people), st.sampled_from(people)).filter(lambda t: t[0] != t[1]),
    st.integers(1, 10**6),
    max_size=12,
).map(lambda d: {k: v for k, v in d.items() if (k[1], k[0]) not in d or k < (k[1], k[0])})
unfriended = st.sets(st.sampled_from(list(combinations(people, 2))), max_size=6)


@settings(max_examples=500)
@given(plain_debts, unfriended)
def test_positions_never_change_and_only_friends_pay(plain, removed) -> None:
    def friends(a: str, b: str) -> bool:
        return tuple(sorted((a, b))) not in removed

    nets = nets_of(plain)
    result = simplify(nets, plain, friends)
    assert nets_of(result) == nets
    assert all(amount > 0 for amount in result.values())
    # Every payment is between friends, or was already a plain debt.
    assert all(friends(a, b) or (a, b) in plain for (a, b) in result)
    # Never more payments, nor more money moved, than the plain debts.
    assert len(result) <= len(plain)
    assert sum(result.values()) <= sum(plain.values())


@settings(max_examples=500)
@given(plain_debts)
def test_all_friends_needs_at_most_n_minus_1_payments(plain) -> None:
    nets = nets_of(plain)
    result = simplify(nets, plain, everyone)
    involved = [p for p, n in nets.items() if n]
    assert len(result) <= max(len(involved) - 1, 0)
    # Money only flows from people who owe overall to people who are owed overall.
    assert all(nets[a] < 0 < nets[b] for (a, b) in result)
