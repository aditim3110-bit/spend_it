"""Who owes whom within one expense (PRD section 8; decided 2026-11-17).

Rule: only people who are short pay, and they pay the people who are out of pocket.

Example: a S$300 hotel split three ways (S$100 each). Aditi paid S$200, Ben paid S$100.
  Nets: Aditi +100 (out of pocket), Ben 0 (square), Chen -100 (short).
  Result: Chen owes Aditi S$100. Ben owes nobody and is owed nothing.

With one payer this is just "everyone owes the payer their share".

With several short and several out-of-pocket people, each short person's debt is spread
across the out-of-pocket people in proportion to what each is still owed. Short people
are handled one at a time in ID order, each against what's *still* owed, so every short
person pays exactly their debt and every out-of-pocket person receives exactly what
they're owed: no stray cent anywhere. Fractions of a cent are settled with the same
largest-remainder rounding as splits, ties by ID, so the result is the same everywhere.
"""

from collections.abc import Mapping

from app.services.split_engine.allocate import largest_remainder


def pairwise_debts(nets: Mapping[str, int]) -> dict[tuple[str, str], int]:
    """{(debtor, creditor): amount} from each person's net (paid - owed) on one expense.

    Every amount is > 0. Raises ValueError if the nets don't sum to zero.
    """
    if sum(nets.values()) != 0:
        raise ValueError("nets must sum to zero")
    debtors = sorted((pid, -net) for pid, net in nets.items() if net < 0)
    still_owed = {pid: net for pid, net in sorted(nets.items()) if net > 0}

    debts: dict[tuple[str, str], int] = {}
    for debtor, debt in debtors:
        weights = [(creditor, owed) for creditor, owed in still_owed.items() if owed > 0]
        # The total still owed is always >= this debt, so no creditor gets more than
        # they're still owed; the last debtor pays off exactly what's left.
        for creditor, amount in largest_remainder(debt, weights).items():
            if amount:
                debts[(debtor, creditor)] = amount
                still_owed[creditor] -= amount
    return debts
