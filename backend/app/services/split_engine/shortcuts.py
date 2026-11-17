"""The four two-person shortcuts (PRD section 7).

They only build an ordinary SplitRequest; the saved expense is identical to one entered
through the full split editor. "Split equally" is stored as EQUAL, "owed the full amount"
as EXACT (with a 0 row for the person who owes nothing).
"""

from enum import StrEnum

from app.services.split_engine.types import Payer, ShareInput, SplitMode, SplitRequest


class TwoPersonShortcut(StrEnum):
    YOU_PAID_SPLIT_EQUALLY = "you_paid_split_equally"
    YOU_ARE_OWED_FULL = "you_are_owed_full"
    THEY_PAID_SPLIT_EQUALLY = "they_paid_split_equally"
    THEY_ARE_OWED_FULL = "they_are_owed_full"


def two_person(
    shortcut: TwoPersonShortcut, you: str, other: str, total: int, currency: str
) -> SplitRequest:
    you_paid = shortcut in (
        TwoPersonShortcut.YOU_PAID_SPLIT_EQUALLY,
        TwoPersonShortcut.YOU_ARE_OWED_FULL,
    )
    payer, debtor = (you, other) if you_paid else (other, you)

    if shortcut in (
        TwoPersonShortcut.YOU_PAID_SPLIT_EQUALLY,
        TwoPersonShortcut.THEY_PAID_SPLIT_EQUALLY,
    ):
        mode = SplitMode.EQUAL
        inputs = (ShareInput(you), ShareInput(other))
    else:
        mode = SplitMode.EXACT
        owed = {payer: 0, debtor: total}
        inputs = (ShareInput(you, owed[you]), ShareInput(other, owed[other]))

    return SplitRequest(
        total=total, currency=currency, payers=(Payer(payer, total),), mode=mode, inputs=inputs
    )
