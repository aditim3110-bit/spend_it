"""Largest-remainder (Hamilton) rounding, PRD section 7.

Example: S$100.00 (10000 cents) split equally 3 ways, Ben paid.
  Each exact share is 3333.33...  ->  everyone gets 3333 (the whole part).
  3 x 3333 = 9999, so 1 cent is left over.
  Everyone's fraction is the same .33 (a tie), so the payer, Ben, gets it.
  Result: Aditi 3333, Ben 3334, Chen 3333.

Fractions are compared as exact integers (the remainder of total*w / W),
never as floats, so there is no floating-point error and Swift matches exactly.
"""

from collections.abc import Sequence


def largest_remainder(
    total: int,
    weights: Sequence[tuple[str, int]],
    priority_id: str | None = None,
) -> dict[str, int]:
    """Split `total` in proportion to `weights` so the parts add up exactly to `total`.

    Each leftover unit goes to the participant with the largest fractional remainder.
    Exact ties go to `priority_id` first (the single payer, if any), then by ID ascending.
    Nobody ends up more than 1 unit away from their exact share.

    The caller guarantees: total >= 0, weights non-negative, sum of weights > 0, unique IDs.
    """
    weight_sum = sum(w for _, w in weights)
    owed: dict[str, int] = {}
    remainders: list[tuple[str, int]] = []
    for pid, w in weights:
        whole, remainder = divmod(total * w, weight_sum)
        owed[pid] = whole
        remainders.append((pid, remainder))

    leftover = total - sum(owed.values())  # always smaller than the number of people

    def tie_order(item: tuple[str, int]) -> tuple[int, bool, str]:
        pid, remainder = item
        # Biggest remainder first; then the priority person; then lowest ID.
        return (-remainder, pid != priority_id, pid)

    for pid, _ in sorted(remainders, key=tie_order)[:leftover]:
        owed[pid] += 1
    return owed
