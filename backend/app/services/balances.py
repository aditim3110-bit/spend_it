"""Balances: who owes whom (PRD section 8).

A balance between two people is the sum, over every live expense they share, of what
that expense makes one owe the other (see split_engine/pairwise.py for the rule when
several people paid). Currencies are never added together.

The `balances` table caches these sums. ExpenseService keeps it up to date in the same
transaction as each write (revision_deltas below); the audit rebuilds it from scratch
with expected_from_ledger and repairs any difference.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.models import Expense, User
from app.models.expense import ContextType
from app.repositories import balances as repo
from app.repositories import expenses as expense_repo
from app.repositories import friends as friend_repo
from app.repositories import groups as group_repo
from app.repositories import users as user_repo
from app.repositories.balances import Key
from app.repositories.expenses import RevisionData, RevisionRows
from app.services.simplify import simplify
from app.services.split_engine import pairwise_debts

Deltas = dict[Key, int]


# --- From the ledger to balance changes ---------------------------------------------------


def _deltas(
    context: tuple[ContextType, uuid.UUID | None],
    currency: str,
    paid: Iterable[tuple[uuid.UUID, int]],
    owed: Iterable[tuple[uuid.UUID, int]],
    sign: int,
) -> Deltas:
    nets: dict[str, int] = defaultdict(int)
    for uid, amount in paid:
        nets[str(uid)] += amount
    for uid, amount in owed:
        nets[str(uid)] -= amount
    deltas: Deltas = defaultdict(int)
    for (debtor, creditor), amount in pairwise_debts(nets).items():
        d, c = uuid.UUID(debtor), uuid.UUID(creditor)
        a, b = (d, c) if d < c else (c, d)
        # Stored as "b owes a" when positive.
        signed = amount if d == b else -amount
        key = Key(context[0], context[1], a, b, currency)
        deltas[key] += sign * signed
    return dict(deltas)


def data_deltas(expense: Expense, data: RevisionData, sign: int) -> Deltas:
    """Balance changes for a version about to be saved under `expense`'s context."""
    return _deltas(
        (expense.context_type, expense.group_id),
        data.currency,
        data.payers,
        ((uid, owed) for uid, owed, _ in data.shares),
        sign,
    )


def rows_deltas(rows: RevisionRows, sign: int) -> Deltas:
    """Balance changes for a saved version: +1 to count it, -1 to take it back out. Uses
    the context recorded on that version, so moves between groups stay correct."""
    if any(r.user_id is None for r in (*rows.payers, *rows.shares)):
        raise RuntimeError("guest rows can't be in balances yet")  # arrives with guest links
    return _deltas(
        (rows.revision.context_type, rows.revision.group_id),
        rows.revision.currency,
        ((p.user_id, p.amount_minor) for p in rows.payers),  # type: ignore[misc]
        ((s.user_id, s.owed_minor) for s in rows.shares),  # type: ignore[misc]
        sign,
    )


def merge(*parts: Deltas) -> Deltas:
    total: Deltas = defaultdict(int)
    for part in parts:
        for key, amount in part.items():
            total[key] += amount
    return {k: v for k, v in total.items() if v}


async def expected_from_ledger(
    session: AsyncSession, skip: set[uuid.UUID] | frozenset[uuid.UUID] = frozenset()
) -> Deltas:
    """Rebuild every balance from scratch: the current version of every live expense.
    `skip` leaves out revisions the audit found broken (they can't be split into debts)."""
    expenses = list(
        (await session.execute(select(Expense).where(Expense.deleted_at.is_(None)))).scalars()
    )
    expected: list[Deltas] = []
    batch = 500
    for start in range(0, len(expenses), batch):
        chunk = expenses[start : start + batch]
        ids = [
            e.current_revision_id
            for e in chunk
            if e.current_revision_id and e.current_revision_id not in skip
        ]
        loaded = await expense_repo.load_revisions(session, ids)
        expected += [rows_deltas(loaded[i], +1) for i in ids]
    return merge(*expected)


async def owed_between(
    session: AsyncSession, payer: uuid.UUID, receiver: uuid.UUID, currency: str
) -> int:
    """How much `payer` owes `receiver` in this currency, across every context (PRD
    section 8, "one payment per person"). Zero or negative means nothing is owed."""
    rows = await repo.between(session, payer, receiver)
    return sum(
        _from_my_side(receiver, b.party_a, b.amount_minor) for b in rows if b.currency == currency
    )


# --- Groups: plain debts and Smart Settle -------------------------------------------------


Transfer = tuple[uuid.UUID, uuid.UUID, str, int]  # payer, receiver, currency, amount


@dataclass
class GroupView:
    nets: dict[uuid.UUID, dict[str, int]]  # member -> currency -> overall position
    transfers: list[Transfer]  # who pays whom to settle the group


async def group_view(session: AsyncSession, group_id: uuid.UUID, smart: bool) -> GroupView:
    """The group's balances. With `smart` (Smart Settle), the fewest payments that settle
    everyone, only ever between friends; otherwise the plain debts (PRD section 8)."""
    plain: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    nets: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for b in await repo.in_group(session, group_id):
        # Stored as "b owes a" when positive.
        debtor, creditor = (b.party_b, b.party_a) if b.amount_minor > 0 else (b.party_a, b.party_b)
        amount = abs(b.amount_minor)
        plain[b.currency][(str(debtor), str(creditor))] = amount
        nets[debtor][b.currency] -= amount
        nets[creditor][b.currency] += amount

    friends: set[frozenset[uuid.UUID]] = set()
    if smart:
        friends = await friend_repo.pairs_among(session, set(nets))

    def are_friends(a: str, b: str) -> bool:
        return frozenset((uuid.UUID(a), uuid.UUID(b))) in friends

    transfers: list[Transfer] = []
    for currency in sorted(plain):
        if smart:
            by_person = {str(p): n[currency] for p, n in nets.items() if n.get(currency)}
            payments = simplify(by_person, plain[currency], are_friends)
        else:
            payments = plain[currency]
        transfers += [
            (uuid.UUID(a), uuid.UUID(b), currency, amount)
            for (a, b), amount in sorted(payments.items())
        ]
    clean = {p: {c: a for c, a in sorted(n.items()) if a} for p, n in nets.items()}
    return GroupView(nets={p: n for p, n in clean.items() if n}, transfers=transfers)


Lines = dict[tuple[str, uuid.UUID | None], dict[uuid.UUID, dict[str, int]]]


async def my_lines(session: AsyncSession, user_id: uuid.UUID) -> Lines:
    """What each person owes this user (positive) or is owed (negative), per context and
    currency. Direct balances are the plain debts; each group contributes what *that
    group* says: its Smart Settle payments when it's on, the plain debts when it's off
    (PRD section 8, "one payment per person, across everything")."""
    lines: Lines = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    groups: set[uuid.UUID] = set()
    for b in await repo.for_user(session, user_id):
        if b.group_id is not None:
            groups.add(b.group_id)
            continue
        other = b.party_b if b.party_a == user_id else b.party_a
        lines[("direct", None)][other][b.currency] += _from_my_side(
            user_id, b.party_a, b.amount_minor
        )
    for group_id in sorted(groups, key=str):
        group = await group_repo.get(session, group_id)
        view = await group_view(session, group_id, smart=bool(group and group.simplify_debts))
        for payer, receiver, currency, amount in view.transfers:
            if receiver == user_id:
                lines[("group", group_id)][payer][currency] += amount
            elif payer == user_id:
                lines[("group", group_id)][receiver][currency] -= amount
    return lines


# --- Reading balances ---------------------------------------------------------------------


@dataclass
class PersonBalance:
    user_id: uuid.UUID
    display_name: str | None
    amounts: dict[str, int]  # currency -> amount; positive means they owe you


@dataclass
class Summary:
    totals: dict[str, tuple[int, int]]  # currency -> (owed to you, you owe)
    people: list[PersonBalance]


@dataclass
class ContextBalance:
    context_type: str
    group_id: uuid.UUID | None
    amounts: dict[str, int] = field(default_factory=dict)


@dataclass
class GroupScreen:
    smart_settle: bool
    view: str
    balances: GroupView
    people: list[tuple[uuid.UUID, str | None]]  # (user id, name)


@dataclass
class WithPerson:
    person: PersonBalance
    contexts: list[ContextBalance]


def _from_my_side(user_id: uuid.UUID, party_a: uuid.UUID, amount: int) -> int:
    """Positive means the other person owes me."""
    return amount if user_id == party_a else -amount


class BalanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, user: User) -> Summary:
        per_person: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for people in (await my_lines(self._session, user.id)).values():
            for other, amounts in people.items():
                for currency, amount in amounts.items():
                    per_person[other][currency] += amount

        users = await user_repo.get_users(self._session, set(per_person))
        people: list[PersonBalance] = []
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for uid, amounts in per_person.items():
            nonzero = {cur: amt for cur, amt in sorted(amounts.items()) if amt}
            if not nonzero:
                continue
            for cur, amt in nonzero.items():
                totals[cur][0 if amt > 0 else 1] += abs(amt)
            people.append(PersonBalance(uid, users[uid].display_name, nonzero))
        people.sort(key=lambda p: ((p.display_name or "").casefold(), str(p.user_id)))
        return Summary(
            totals={cur: (owed, owe) for cur, (owed, owe) in sorted(totals.items())},
            people=people,
        )

    async def for_group(self, user: User, group_id: uuid.UUID, view: str | None) -> GroupScreen:
        """A group's balance screen, for members. `view`: "simplified" or "detailed";
        by default simplified when Smart Settle is on."""
        group = await group_repo.get(self._session, group_id)
        if group is None or not await group_repo.membership(self._session, group_id, user.id):
            raise ProblemError(404, "not-found", "Group not found.")
        chosen = view or ("simplified" if group.simplify_debts else "detailed")
        balances = await group_view(self._session, group_id, chosen == "simplified")
        # Current members first (in join order), then anyone else with money still open.
        members = [m.user_id for m, _ in await group_repo.members(self._session, group_id)]
        ids = list(dict.fromkeys([*members, *sorted(balances.nets, key=str)]))
        users = await user_repo.get_users(self._session, set(ids))
        return GroupScreen(
            smart_settle=group.simplify_debts,
            view=chosen,
            balances=balances,
            people=[(uid, users[uid].display_name if uid in users else None) for uid in ids],
        )

    async def with_person(self, user: User, other_id: uuid.UUID) -> WithPerson:
        other = await user_repo.get_user(self._session, other_id)
        if other is None or other_id == user.id:
            raise ProblemError(404, "not-found", "Person not found.")
        contexts: dict[tuple[str, uuid.UUID | None], ContextBalance] = {}
        overall: dict[str, int] = defaultdict(int)
        lines = await my_lines(self._session, user.id)
        for (context_type, group_id), people in sorted(lines.items(), key=lambda kv: str(kv[0])):
            for currency, amount in people.get(other_id, {}).items():
                if not amount:
                    continue
                ctx = contexts.setdefault(
                    (context_type, group_id), ContextBalance(context_type, group_id)
                )
                ctx.amounts[currency] = amount
                overall[currency] += amount
        return WithPerson(
            person=PersonBalance(
                other.id,
                other.display_name,
                {cur: amt for cur, amt in sorted(overall.items()) if amt},
            ),
            contexts=list(contexts.values()),
        )
