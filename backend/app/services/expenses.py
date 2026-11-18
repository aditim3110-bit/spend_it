"""Expenses: create, view, list, edit, delete, restore, history (PRD sections 7, 9, 17;
decisions of 2026-11-17 and 2026-11-18).

Direct expenses (no group):
- The person adding or editing must be on the expense (paid, or owes).
- Everyone else on a new expense must be their friend. In an edit, only newly added
  people are checked: someone already on the expense stays even if a friendship ended,
  because money facts aren't hidden.
- Everyone on the expense must have set their name.
- The split engine computes who owes what; the server saves its result, never the app's.
- People on a shared expense become friends automatically (source "expense").
- Anyone in the current version can edit, delete and restore (30 days). Anyone who was
  ever on it can still view it and its history.
- The last save wins: an edit always applies on top of the latest version, even if the
  person opened an older one. Nothing is lost, because every version stays in the history.

Group expenses:
- Any current member can add, edit, delete or restore one, even if they're not on it.
- Everyone on it must be a current member; nobody is added to the group automatically.
- If anyone on it has left the group, it's locked (no edit, delete or restore), so
  nobody gets a debt in a group they're no longer in.
- Archived groups are read-only.
- Current members can see every group expense; anyone ever on one can still see it.
- No friendship checks or auto-friending: joining the group already made them friends.
- An expense never changes group through an edit (moving is a separate action).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import pagination
from app.core.errors import ProblemError
from app.core.split_errors import split_problem
from app.models import Expense, FriendSource, Group, User
from app.models.expense import ExpenseKind, RevisionReason, SplitModeDb
from app.repositories import balances as balance_repo
from app.repositories import expenses as repo
from app.repositories import friends as friend_repo
from app.repositories import groups as group_repo
from app.repositories import users as user_repo
from app.repositories.expenses import RevisionData, RevisionRows
from app.schemas.expenses import ExpenseIn, ExpenseStatus
from app.services.balances import data_deltas, merge, rows_deltas
from app.services.split_engine import (
    Payer,
    ShareInput,
    SplitError,
    SplitRequest,
    compute_split,
)

RESTORE_WINDOW = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class ExpenseView:
    expense: Expense
    current: RevisionRows
    names: dict[uuid.UUID, str | None]


@dataclass(frozen=True, slots=True)
class ExpensePage:
    items: list[ExpenseView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class History:
    revisions: list[RevisionRows]  # oldest first
    names: dict[uuid.UUID, str | None]


class ExpenseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Writes ---------------------------------------------------------------------------

    async def create(self, user: User, body: ExpenseIn) -> ExpenseView:
        _require_name(user)
        data = _compute(body)
        people = data.people()
        if body.group_id is None:
            await self._check_people(user, people, already_on=set())
            expense = await repo.create(self._session, user.id, data)
            await self._befriend(people, newly_added=people)
        else:
            group = await self._writable_group(user, body.group_id)
            await self._check_members(group, people)
            expense = await repo.create(self._session, user.id, data, group_id=group.id)
        await balance_repo.apply(self._session, data_deltas(expense, data, +1))
        await self._session.commit()
        return await self._view(expense.id)

    async def edit(self, user: User, expense_id: uuid.UUID, body: ExpenseIn) -> ExpenseView:
        _require_name(user)
        expense, current = await self._for_change(user, expense_id)
        if expense.kind is ExpenseKind.SETTLEMENT:
            raise ProblemError(
                409, "is-a-settlement", "This is a payment. Edit it with PUT /v1/settlements/{id}."
            )
        if expense.deleted_at is not None:
            raise ProblemError(
                409, "expense-deleted", "This expense was deleted. Restore it to edit it."
            )
        if body.group_id != expense.group_id:
            raise ProblemError(
                409, "use-move", "An expense can't change group in an edit. Move it instead."
            )
        data = _compute(body)
        people = data.people()
        before = current.people()
        if expense.group_id is None:
            await self._check_people(user, people, already_on=before)
        else:
            group = await group_repo.get(self._session, expense.group_id)
            await self._check_members(group, people)  # type: ignore[arg-type]
        await repo.add_revision(
            self._session, expense, user.id, current.revision.rev_no + 1, RevisionReason.EDIT, data
        )
        # Take the old version out of the balances and put the new one in, as one change.
        await balance_repo.apply(
            self._session, merge(rows_deltas(current, -1), data_deltas(expense, data, +1))
        )
        if expense.group_id is None:
            await self._befriend(people, newly_added=people - before)
        await self._session.commit()
        return await self._view(expense.id)

    async def delete(self, user: User, expense_id: uuid.UUID) -> None:
        """Soft delete. Deleting an already deleted expense succeeds and changes nothing."""
        expense, current = await self._for_change(user, expense_id)
        if expense.deleted_at is None:
            await repo.set_deleted(self._session, expense, datetime.now(UTC), user.id)
            await balance_repo.apply(self._session, rows_deltas(current, -1))
        await self._session.commit()

    async def restore(self, user: User, expense_id: uuid.UUID) -> ExpenseView:
        """Undo a delete within 30 days. Restoring a live expense succeeds and changes
        nothing."""
        expense, current = await self._for_change(user, expense_id)
        if expense.deleted_at is not None:
            if datetime.now(UTC) - expense.deleted_at > RESTORE_WINDOW:
                raise ProblemError(
                    409,
                    "restore-window-passed",
                    "Deleted expenses can only be restored for 30 days.",
                )
            await repo.set_deleted(self._session, expense, None, None)
            await balance_repo.apply(self._session, rows_deltas(current, +1))
        await self._session.commit()
        return await self._view(expense.id)

    # --- Reads ----------------------------------------------------------------------------

    async def get(self, user: User, expense_id: uuid.UUID) -> ExpenseView:
        expense = await self._visible(user, expense_id)
        return await self._view(expense.id, expense)

    async def page(
        self,
        user: User,
        *,
        friend_id: uuid.UUID | None,
        status: ExpenseStatus,
        limit: int,
        cursor: str | None,
        group_id: uuid.UUID | None = None,
    ) -> ExpensePage:
        if group_id is not None and not await group_repo.membership(
            self._session, group_id, user.id
        ):
            raise ProblemError(404, "not-found", "Group not found.")
        after = pagination.decode_dated(cursor) if cursor else None
        since = None if status == "live" else datetime.now(UTC) - RESTORE_WINDOW
        rows = await repo.feed(
            self._session,
            user.id,
            friend_id=friend_id,
            deleted_since=since,
            limit=limit + 1,
            after=after,
            group_id=group_id,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = await self._views(rows)
        next_cursor = None
        if has_more:
            last = rows[-1]
            next_cursor = pagination.encode_dated(last.expense_date, last.created_at, last.id)
        return ExpensePage(items=items, next_cursor=next_cursor)

    async def history(self, user: User, expense_id: uuid.UUID) -> History:
        await self._visible(user, expense_id)
        ids = await repo.revision_ids(self._session, expense_id)
        loaded = await repo.load_revisions(self._session, ids)
        revisions = [loaded[i] for i in ids]
        people = set().union(*(r.people() for r in revisions))
        return History(revisions=revisions, names=await self._names(people))

    # --- Helpers --------------------------------------------------------------------------

    async def _visible(self, user: User, expense_id: uuid.UUID, *, lock: bool = False) -> Expense:
        """The expense, if this person was ever on it or is in its group now. Otherwise 404,
        so nobody can learn that an expense exists by guessing IDs."""
        expense = await repo.get(self._session, expense_id, lock=lock)
        if expense is None:
            raise ProblemError(404, "not-found", "Expense not found.")
        if expense.group_id is not None and await group_repo.membership(
            self._session, expense.group_id, user.id
        ):
            return expense
        if not await repo.ever_involved(self._session, expense_id, user.id):
            raise ProblemError(404, "not-found", "Expense not found.")
        return expense

    async def _for_change(self, user: User, expense_id: uuid.UUID) -> tuple[Expense, RevisionRows]:
        """Lock the expense for a change, checking this person may change it."""
        expense = await self._visible(user, expense_id, lock=True)
        current = await self._current(expense)
        if expense.group_id is None:
            if user.id not in current.people():
                raise ProblemError(
                    403,
                    "not-a-participant",
                    "You're no longer on this expense, so you can't change it.",
                )
            return expense, current
        group = await group_repo.get(self._session, expense.group_id)
        members = await group_repo.member_ids(self._session, expense.group_id)
        if user.id not in members:
            raise ProblemError(
                403, "not-a-member", "You're no longer in this group, so you can't change this."
            )
        _require_active(group)  # type: ignore[arg-type]
        await self._refuse_former_members(current.people() - members)
        return expense, current

    async def _writable_group(self, user: User, group_id: uuid.UUID) -> Group:
        """The group, if this person is in it now and it isn't archived."""
        group = await group_repo.get(self._session, group_id)
        if group is None or not await group_repo.membership(self._session, group_id, user.id):
            raise ProblemError(404, "not-found", "Group not found.")
        _require_active(group)
        return group

    async def _check_members(self, group: Group, people: set[uuid.UUID]) -> None:
        """Everyone on a group expense must be in the group now."""
        members = await group_repo.member_ids(self._session, group.id)
        outsiders = sorted(str(p) for p in people - members)
        if outsiders:
            raise ProblemError(
                422,
                "not-members",
                "Everyone on a group expense must be in the group. Add them to the group first.",
                errors=[{"user_id": o} for o in outsiders],
            )

    async def _refuse_former_members(self, left: set[uuid.UUID]) -> None:
        if not left:
            return
        names = await self._names(left)
        who = ", ".join(sorted(n or "Someone" for n in names.values()))
        raise ProblemError(
            409,
            "former-member",
            f"{who} left this group. Add them back to change this expense.",
            errors=[{"user_id": str(u)} for u in sorted(left, key=str)],
        )

    async def _current(self, expense: Expense) -> RevisionRows:
        if expense.current_revision_id is None:  # only true mid-transaction during create
            raise RuntimeError(f"expense {expense.id} has no current revision")
        loaded = await repo.load_revisions(self._session, [expense.current_revision_id])
        return loaded[expense.current_revision_id]

    async def _check_people(
        self, user: User, people: set[uuid.UUID], *, already_on: set[uuid.UUID]
    ) -> None:
        if user.id not in people:
            raise ProblemError(
                422,
                "not-involved",
                "You can only add expenses you're part of: you paid, or you owe a share.",
            )
        users = await user_repo.get_users(self._session, people)
        unknown = sorted(str(p) for p in people - users.keys())
        if unknown:
            raise ProblemError(
                422,
                "unknown-user",
                "Some people on this expense don't have a SpendIt account.",
                errors=[{"user_id": u} for u in unknown],
            )
        nameless = sorted(str(u.id) for u in users.values() if u.display_name is None)
        if nameless:
            raise ProblemError(
                422,
                "name-required",
                "Some people haven't finished signing up (no name yet).",
                errors=[{"user_id": u} for u in nameless],
            )
        newcomers = people - already_on - {user.id}
        friends = await friend_repo.friends_among(self._session, user.id, newcomers)
        strangers = sorted(str(p) for p in newcomers - friends)
        if strangers:
            raise ProblemError(
                422,
                "not-friends",
                "You can only add friends to an expense. Add them as a friend first.",
                errors=[{"user_id": s} for s in strangers],
            )

    async def _befriend(self, people: set[uuid.UUID], *, newly_added: set[uuid.UUID]) -> None:
        """Everyone on a shared expense becomes friends. Only pairs involving someone new
        are created, so an edit never re-adds a friendship someone deliberately removed."""
        pairs = {(a, b) for a in newly_added for b in people if a != b}
        await friend_repo.connect_many(self._session, pairs, FriendSource.EXPENSE)

    async def _view(self, expense_id: uuid.UUID, expense: Expense | None = None) -> ExpenseView:
        if expense is None:
            expense = await repo.get(self._session, expense_id)
            if expense is None:
                raise RuntimeError(f"expense {expense_id} vanished")
        return (await self._views([expense]))[0]

    async def _views(self, expenses: list[Expense]) -> list[ExpenseView]:
        rev_ids = [e.current_revision_id for e in expenses if e.current_revision_id]
        loaded = await repo.load_revisions(self._session, rev_ids)
        people = set().union(*(r.people() for r in loaded.values()))
        names = await self._names(people)
        return [
            ExpenseView(expense=e, current=loaded[e.current_revision_id], names=names)  # type: ignore[index]
            for e in expenses
        ]

    async def _names(self, people: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
        users = await user_repo.get_users(self._session, people)
        return {uid: u.display_name for uid, u in users.items()}


def _compute(body: ExpenseIn) -> RevisionData:
    """Run the split engine on what the person typed. The engine's result is what we save."""
    request = SplitRequest(
        total=body.amount_minor,
        currency=body.currency,
        payers=tuple(Payer(str(p.user_id), p.amount_minor) for p in body.payers),
        mode=body.split.mode,
        inputs=tuple(ShareInput(str(s.user_id), s.value) for s in body.split.shares),
    )
    try:
        result = compute_split(request)
    except SplitError as err:
        raise split_problem(err) from None
    except ValueError as err:  # a value missing for exact/percent/shares
        raise ProblemError(422, "validation-error", str(err)) from None
    return RevisionData(
        name=body.name,
        amount_minor=result.total,
        currency=result.currency,
        expense_date=body.expense_date,
        split_mode=SplitModeDb(result.mode.value),
        notes=body.notes,
        payers=[(uuid.UUID(p.id), p.amount) for p in result.payers],
        shares=[(uuid.UUID(s.id), s.owed, s.input_value) for s in result.shares],
    )


def _require_name(user: User) -> None:
    if user.display_name is None:
        raise ProblemError(
            422, "name-required", "Set your name first, so friends know who you are."
        )


def _require_active(group: Group) -> None:
    if group.archived_at is not None:
        raise ProblemError(409, "group-archived", "This group is archived. Unarchive it first.")
