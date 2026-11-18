"""Recording payments: "Aditi paid Ben S$20" (PRD section 8; decisions of 2026-11-17).

A payment is stored in the same ledger as expenses, as kind "settlement": Aditi is the one
payer and Ben the one person "owing" the amount. On balances that cancels out S$20 of
what Aditi owed Ben. Payments reduce the balance, not a particular expense, so if an
expense is edited later the balance simply moves (e.g. Ben paid S$10, the dinner went up
from S$20 to S$30, so Ben owes S$5 more).

Rules:
- Either the payer or the receiver can record it, edit it, delete it or restore it.
  Deleting is how a wrong payment is disputed; the debt comes back.
- Any amount is allowed: a payment is simply money that moved. If Chen owes Aditi S$33.33
  and pays S$50, Aditi then owes Chen S$16.67. Paying someone you owe nothing works the
  same way (they then owe you).
- How it was paid (cash, bank, PayNow...) isn't recorded.
- Friendship isn't required: paying back someone you've unfriended still works.
"""

import uuid

from app.core.errors import ProblemError
from app.core.split_errors import split_problem
from app.models import User
from app.models.expense import ExpenseKind, RevisionReason, SplitModeDb
from app.repositories import balances as balance_repo
from app.repositories import expenses as repo
from app.repositories import users as user_repo
from app.repositories.expenses import RevisionData
from app.schemas.settlements import SettlementEditIn, SettlementIn
from app.services.balances import data_deltas, merge, rows_deltas
from app.services.expenses import ExpenseService, ExpenseView, _require_name
from app.services.split_engine import (
    Payer,
    ShareInput,
    SplitError,
    SplitMode,
    SplitRequest,
    compute_split,
)

PAYMENT_NAME = "Payment"


class SettlementService(ExpenseService):
    """Shares the expense helpers (who can see and change what) with ExpenseService."""

    async def record(self, user: User, body: SettlementIn) -> ExpenseView:
        _require_name(user)
        payer, receiver = body.payer_id, body.receiver_id
        if payer == receiver:
            raise ProblemError(422, "same-person", "Someone can't pay themselves back.")
        if user.id not in (payer, receiver):
            raise ProblemError(
                422, "not-involved", "You can only record payments you made or received."
            )
        await self._check_users({payer, receiver})
        data = _payment(payer, receiver, body.amount_minor, body.currency, body)
        expense = await repo.create(self._session, user.id, data, kind=ExpenseKind.SETTLEMENT)
        await balance_repo.apply(self._session, data_deltas(expense, data, +1))
        await self._session.commit()
        return await self._view(expense.id)

    async def edit_payment(
        self, user: User, expense_id: uuid.UUID, body: SettlementEditIn
    ) -> ExpenseView:
        _require_name(user)
        expense, current = await self._for_change(user, expense_id)
        if expense.kind is not ExpenseKind.SETTLEMENT:
            raise ProblemError(
                409, "not-a-settlement", "This is an expense. Edit it with PUT /v1/expenses/{id}."
            )
        if expense.deleted_at is not None:
            raise ProblemError(
                409, "expense-deleted", "This payment was deleted. Restore it to edit it."
            )
        [old_payer] = current.payers
        [old_receiver] = current.shares
        payer, receiver = old_payer.user_id, old_receiver.user_id
        assert payer is not None and receiver is not None  # noqa: S101 - guests can't pay yet
        currency = current.revision.currency
        data = _payment(payer, receiver, body.amount_minor, currency, body)
        await repo.add_revision(
            self._session, expense, user.id, current.revision.rev_no + 1, RevisionReason.EDIT, data
        )
        await balance_repo.apply(
            self._session, merge(rows_deltas(current, -1), data_deltas(expense, data, +1))
        )
        await self._session.commit()
        return await self._view(expense.id)

    # --- Helpers --------------------------------------------------------------------------

    async def _check_users(self, people: set[uuid.UUID]) -> None:
        users = await user_repo.get_users(self._session, people)
        unknown = sorted(str(p) for p in people - users.keys())
        if unknown:
            raise ProblemError(
                422,
                "unknown-user",
                "That person doesn't have a SpendIt account.",
                errors=[{"user_id": u} for u in unknown],
            )
        nameless = sorted(str(u.id) for u in users.values() if u.display_name is None)
        if nameless:
            raise ProblemError(
                422,
                "name-required",
                "That person hasn't finished signing up (no name yet).",
                errors=[{"user_id": u} for u in nameless],
            )


def _payment(
    payer: uuid.UUID,
    receiver: uuid.UUID,
    amount: int,
    currency: str,
    body: SettlementIn | SettlementEditIn,
) -> RevisionData:
    """The payment as a ledger revision, validated by the split engine like any expense."""
    request = SplitRequest(
        total=amount,
        currency=currency,
        payers=(Payer(str(payer), amount),),
        mode=SplitMode.EXACT,
        inputs=(ShareInput(str(receiver), amount),),
    )
    try:
        result = compute_split(request)
    except SplitError as err:
        raise split_problem(err) from None
    return RevisionData(
        name=PAYMENT_NAME,
        amount_minor=result.total,
        currency=result.currency,
        expense_date=body.expense_date,
        split_mode=SplitModeDb.EXACT,
        notes=body.notes,
        payers=[(payer, amount)],
        shares=[(receiver, amount, amount)],
    )
