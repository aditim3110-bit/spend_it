"""Smart Settle: fewer payments inside a group (PRD section 8; decisions of 2026-11-17).

Input, for one group and one currency:
- `nets`: each member's overall position (positive: they're owed; negative: they owe);
- `plain`: the plain debts, {(debtor, creditor): amount}, which already add up to `nets`;
- `are_friends(a, b)`: Smart Settle only ever tells someone to pay a friend.

Output: the payments to make, {(payer, receiver): amount}. Everyone's overall position is
exactly the same as before; only who pays whom changes. Pure Python with whole minor
units, so there's no rounding.

Usual case: everyone involved is friends (joining a group makes everyone friends). Then
it's the standard method from the PRD: repeatedly match whoever owes the most with
whoever is owed the most (ties by ID), so a group of n people needs at most n-1 payments.
Example: Aditi owes Ben 10 and Ben owes Chen 10 -> Aditi pays Chen 10.

We also shorten chains in the plain debts, only between friends: if A owes B and B owes
C, and A and C are friends, A pays C directly. That method needs no particular
friendships, so it always works, even when someone has removed a friend; and the
matching method can occasionally need more payments than it. We keep whichever result
needs fewer payments, so nobody is ever told to pay someone who isn't their friend, and
Smart Settle is never worse than the plain debts.
"""

from collections.abc import Callable, Mapping

Debts = dict[tuple[str, str], int]


def simplify(
    nets: Mapping[str, int],
    plain: Mapping[tuple[str, str], int],
    are_friends: Callable[[str, str], bool],
) -> Debts:
    if sum(nets.values()) != 0:
        raise ValueError("nets must sum to zero")
    # Two candidates; keep whichever needs fewer payments (then less money moved). The
    # matching one can get stuck when friendships are missing, and either can beat the
    # other, so Smart Settle is never worse than the plain debts.
    candidates = [_shorten_chains(plain, are_friends)]
    matched = _match_biggest(nets, are_friends)
    if matched is not None:
        candidates.append(matched)
    return min(candidates, key=lambda d: (len(d), sum(d.values())))


def _match_biggest(
    nets: Mapping[str, int], are_friends: Callable[[str, str], bool]
) -> Debts | None:
    """The PRD's method: whoever owes the most pays whoever is owed the most among their
    friends (ties by ID). With everyone friends this needs at most n-1 payments. Returns
    None if someone is left owing money with no friend left to pay."""
    owes = {p: -n for p, n in nets.items() if n < 0}
    owed = {p: n for p, n in nets.items() if n > 0}
    payments: Debts = {}
    while owes:
        for debtor in sorted(owes, key=lambda p: (-owes[p], p)):
            friends = [c for c in owed if are_friends(debtor, c)]
            if friends:
                break
        else:
            return None
        creditor = min(friends, key=lambda p: (-owed[p], p))
        amount = min(owes[debtor], owed[creditor])
        payments[(debtor, creditor)] = payments.get((debtor, creditor), 0) + amount
        for side, person in ((owes, debtor), (owed, creditor)):
            side[person] -= amount
            if not side[person]:
                del side[person]
    return payments


class _Graph:
    """Debts with an index of who pays whom, kept up to date as amounts change."""

    def __init__(self) -> None:
        self.debts: Debts = {}
        self.pays: dict[str, set[str]] = {}
        self.paid_by: dict[str, set[str]] = {}

    def add(self, a: str, b: str, amount: int) -> None:
        """Add "a owes b amount", netting against any "b owes a", dropping zeros."""
        net = self._take(a, b) - self._take(b, a) + amount
        if net > 0:
            self._put(a, b, net)
        elif net < 0:
            self._put(b, a, -net)

    def _take(self, a: str, b: str) -> int:
        amount = self.debts.pop((a, b), 0)
        if amount:
            self.pays[a].discard(b)
            self.paid_by[b].discard(a)
        return amount

    def _put(self, a: str, b: str, amount: int) -> None:
        self.debts[(a, b)] = amount
        self.pays.setdefault(a, set()).add(b)
        self.paid_by.setdefault(b, set()).add(a)


def _shorten_chains(
    plain: Mapping[tuple[str, str], int], are_friends: Callable[[str, str], bool]
) -> Debts:
    """While A owes B and B owes C with A and C friends, A pays C directly. Each step
    reduces the total being passed around, so this always finishes."""
    g = _Graph()
    for (a, b), amount in sorted(plain.items()):
        g.add(a, b, amount)
    changed = True
    while changed:
        changed = False
        for b in sorted(g.paid_by):
            for a in sorted(g.paid_by.get(b, ())):
                for c in sorted(g.pays.get(b, ())):
                    if c == a or not are_friends(a, c):
                        continue
                    if (a, b) not in g.debts or (b, c) not in g.debts:
                        continue  # used up earlier in this pass
                    amount = min(g.debts[(a, b)], g.debts[(b, c)])
                    g.add(a, b, -amount)
                    g.add(b, c, -amount)
                    g.add(a, c, amount)
                    changed = True
    return g.debts
