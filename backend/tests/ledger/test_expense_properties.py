"""Property tests for the saved ledger (CLAUDE.md rules 3, 4 and 6).

Hypothesis invents random sequences of "add / edit / delete / restore" by random people
and runs them through the real ExpenseService and Postgres. After each sequence we check
rules that must hold however the expenses were made:

- payments ("settle" steps) leave the pair square when paid in full, and flip it when
  overpaid;
- every saved revision balances: payers = shares = amount;
- what's stored is exactly what the split engine computes from the stored inputs (the
  server decides, and it's reproducible: balances can be rebuilt from revisions);
- revision numbers run 1, 2, 3... and the expense points at the newest one;
- the current state matches a simple in-memory model of what should have happened;
- each group's Smart Settle payments (and its plain debts) keep every member's overall
  position (expenses and payments are randomly direct or in a group everyone is in);
- the balances table equals a rebuild from scratch, and each person's balances add up to
  the sum of what they paid minus what they owe across live expenses (PRD section 8).

Each sequence runs inside a transaction that is rolled back, so nothing is left behind.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import ProblemError
from app.models import FriendSource, User
from app.models.group import GroupType
from app.repositories import balances as balance_repo
from app.repositories import friends as friend_repo
from app.schemas.expenses import ExpenseIn
from app.schemas.groups import GroupCreateIn
from app.schemas.settlements import SettlementIn
from app.services.balances import expected_from_ledger, group_view, owed_between
from app.services.expenses import ExpenseService
from app.services.groups import GroupService
from app.services.settlements import SettlementService
from app.services.split_engine import Payer, ShareInput, SplitMode, SplitRequest, compute_split
from tests.support.database import TEST_DATABASE_URL

PEOPLE = 4
CURRENCIES = ["SGD", "JPY", "KWD"]


# --- Strategies ---------------------------------------------------------------------------


def _partition(draw: st.DrawFn, total: int, parts: int, *, min_part: int) -> list[int]:
    """Split `total` into `parts` integers, each at least `min_part`."""
    spare = total - min_part * parts
    cuts = sorted(draw(st.lists(st.integers(0, spare), min_size=parts - 1, max_size=parts - 1)))
    bounds = [0, *cuts, spare]
    return [min_part + bounds[i + 1] - bounds[i] for i in range(parts)]


@st.composite
def expense_specs(draw: st.DrawFn, actor: int) -> dict[str, Any]:
    """A valid expense body that includes `actor` (people are indexes 0..PEOPLE-1)."""
    others = draw(st.lists(st.integers(0, PEOPLE - 1), unique=True, max_size=PEOPLE - 1))
    people = sorted({actor, *others})
    amount = draw(st.integers(len(people), 1_000_000))
    mode = draw(st.sampled_from(list(SplitMode)))
    if mode is SplitMode.EQUAL:
        values: list[int | None] = [None] * len(people)
    elif mode is SplitMode.EXACT:
        values = list(_partition(draw, amount, len(people), min_part=0))
    elif mode is SplitMode.PERCENT:
        values = list(_partition(draw, 10_000, len(people), min_part=0))
    else:
        values = [draw(st.integers(0, 5)) for _ in people]
        if not any(values):
            values[0] = 1
    payer_ids = draw(st.lists(st.sampled_from(people), unique=True, min_size=1, max_size=2))
    paid = _partition(draw, amount, len(payer_ids), min_part=1)
    return {
        "people": people,
        "amount": amount,
        "currency": draw(st.sampled_from(CURRENCIES)),
        "mode": mode,
        "values": values,
        "payers": list(zip(payer_ids, paid, strict=True)),
        "group": draw(st.booleans()),  # in the group everyone is in, or direct
    }


@st.composite
def operations(draw: st.DrawFn) -> list[tuple]:
    ops: list[tuple] = []
    for _ in range(draw(st.integers(1, 10))):
        actor = draw(st.integers(0, PEOPLE - 1))
        kind = draw(
            st.sampled_from(
                ["create", "create", "edit", "edit", "delete", "restore", "settle", "settle"]
            )
        )
        target = draw(st.integers(0, 7))  # which earlier expense (modulo how many exist)
        if kind in ("create", "edit"):
            spec = draw(expense_specs(actor))
        elif kind == "settle":
            # Pay back one of the debts that exist when the step runs, and what share of
            # it (100 = all of it, 150 = overpaying, which flips who owes whom).
            spec = {
                "pick": draw(st.integers(0, 20)),
                "pct": draw(st.sampled_from([100, 50, 1, 150])),
                "group": draw(st.booleans()),  # recorded inside the group, or direct
            }
        else:
            spec = None
        ops.append((kind, actor, target, spec))
    return ops


# --- The model ----------------------------------------------------------------------------


@dataclass
class Expected:
    id: uuid.UUID
    rev_no: int
    amount: int
    people: set[int]  # in the current version
    ever: set[int]  # in any version (they can still view it)
    deleted: bool
    settlement: bool = False
    group: bool = False  # in the group (any member may change it) rather than direct


def _body(spec: dict[str, Any], users: list[User], group_id: uuid.UUID) -> ExpenseIn:
    return ExpenseIn.model_validate(
        {
            "group_id": group_id if spec["group"] else None,
            "name": "Thing",
            "amount_minor": spec["amount"],
            "currency": spec["currency"],
            "expense_date": date(2026, 11, 17),
            "payers": [{"user_id": users[i].id, "amount_minor": amt} for i, amt in spec["payers"]],
            "split": {
                "mode": spec["mode"],
                "shares": [
                    {"user_id": users[i].id, "value": v}
                    for i, v in zip(spec["people"], spec["values"], strict=True)
                ],
            },
        }
    )


def _payment_in(
    payer: User, receiver: User, amount: int, currency: str, group_id: uuid.UUID | None
) -> SettlementIn:
    return SettlementIn(
        group_id=group_id,
        payer_id=payer.id,
        receiver_id=receiver.id,
        amount_minor=amount,
        currency=currency,
        expense_date=date(2026, 11, 18),
    )


def _people(spec: dict[str, Any]) -> set[int]:
    return set(spec["people"]) | {i for i, _ in spec["payers"]}


async def _run(ops: list[tuple]) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        # The service's commit() only releases a savepoint; the outer rollback undoes all.
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            await _scenario(session, ops)
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


async def _scenario(session: AsyncSession, ops: list[tuple]) -> None:
    users = [User(id=uuid.uuid4(), display_name=f"P{i}") for i in range(PEOPLE)]
    session.add_all(users)
    await session.flush()
    everyone = {u.id for u in users}
    pairs = {(a, b) for a in everyone for b in everyone if a != b}
    await friend_repo.connect_many(session, pairs, FriendSource.QR)
    await session.commit()

    # Everyone is in one group too, so expenses and payments can be direct or in the group.
    group = await GroupService(session).create(
        users[0],
        GroupCreateIn(
            name="G",
            type=GroupType.TRIP,
            default_currency="SGD",
            member_ids=[u.id for u in users[1:]],
        ),
    )
    group_id = group.group.id

    service = ExpenseService(session)
    payments = SettlementService(session)
    model: list[Expected] = []

    for kind, actor, target, spec in ops:
        user = users[actor]
        if kind == "create":
            view = await service.create(user, _body(spec, users, group_id))
            people = _people(spec)
            model.append(
                Expected(
                    view.expense.id, 1, spec["amount"], people, people, False, group=spec["group"]
                )
            )
            continue
        if kind == "settle":
            # Pick one of the debts that exist right now; the person who owes records it.
            debts = [
                (debtor, other, currency, owed)
                for debtor in range(PEOPLE)
                for other in range(PEOPLE)
                if other != debtor
                for currency in CURRENCIES
                if (
                    owed := await owed_between(session, users[debtor].id, users[other].id, currency)
                )
                > 0
            ]
            if not debts:
                continue  # nobody owes anybody anything yet
            debtor, other, currency, owed = debts[spec["pick"] % len(debts)]
            payer, receiver = users[debtor], users[other]
            amount = max(1, owed * spec["pct"] // 100)
            event(f"payment recorded ({spec['pct']}% of the debt)")
            in_group = group_id if spec["group"] else None
            view = await payments.record(
                payer, _payment_in(payer, receiver, amount, currency, in_group)
            )
            pair = {debtor, other}
            model.append(
                Expected(
                    view.expense.id, 1, amount, pair, pair, False,
                    settlement=True, group=spec["group"],
                )
            )  # fmt: skip
            # What's owed afterwards is exactly the old debt minus the payment.
            after = await owed_between(session, payer.id, receiver.id, currency)
            assert after == owed - amount
            continue
        if not model:
            continue
        exp = model[target % len(model)]
        # In the group any member may change it (everyone is a member here); direct
        # expenses only by someone on the current version.
        allowed = exp.group or actor in exp.people
        try:
            if kind == "edit":
                spec = {**spec, "group": exp.group}  # an edit can't change the group
                await service.edit(user, exp.id, _body(spec, users, group_id))
                assert allowed and not exp.deleted and not exp.settlement
                exp.rev_no += 1
                exp.amount = spec["amount"]
                exp.people = _people(spec)
                exp.ever = exp.ever | exp.people
            elif kind == "delete":
                await service.delete(user, exp.id)
                assert allowed
                exp.deleted = True
            else:
                await service.restore(user, exp.id)
                assert allowed
                exp.deleted = False
        except ProblemError as err:
            # The only refusals possible here: never on it (404, as if it didn't exist),
            # no longer on it (403), or editing a deleted one or a payment through the
            # expense route (409). All are raised before anything is written, so the
            # session carries on.
            if not exp.group and actor not in exp.ever:
                expected_status = 404
            elif not allowed:
                expected_status = 403
            else:
                expected_status = 409
            assert err.status == expected_status, (kind, err.status, err.detail)

    await _check_invariants(session, model, users)
    await _check_group(session, group_id)


async def _check_group(session: AsyncSession, group_id: uuid.UUID) -> None:
    """Smart Settle's payments keep every member's overall position in the group, and so
    do the plain debts."""
    for smart in (True, False):
        view = await group_view(session, group_id, smart)
        moved: dict[tuple[uuid.UUID, str], int] = {}
        for payer, receiver, currency, amount in view.transfers:
            assert amount > 0
            moved[(payer, currency)] = moved.get((payer, currency), 0) - amount
            moved[(receiver, currency)] = moved.get((receiver, currency), 0) + amount
        expected = {(p, c): a for p, n in view.nets.items() for c, a in n.items()}
        assert {k: v for k, v in moved.items() if v} == expected


async def _check_invariants(
    session: AsyncSession, model: list[Expected], users: list[User]
) -> None:
    index = {u.id: i for i, u in enumerate(users)}

    # Every revision balances and equals the engine's output on its own stored inputs.
    revisions = (
        await session.execute(
            text(
                "SELECT r.id, r.expense_id, r.rev_no, r.amount_minor, r.currency, r.split_mode "
                "FROM expense_revisions r WHERE r.created_by = ANY(:ids) ORDER BY r.rev_no"
            ),
            {"ids": [u.id for u in users]},
        )
    ).all()
    by_expense: dict[uuid.UUID, list[int]] = {}
    for rev_id, expense_id, rev_no, amount, currency, mode in revisions:
        by_expense.setdefault(expense_id, []).append(rev_no)
        payers = (
            await session.execute(
                text("SELECT user_id, amount_minor FROM expense_payers WHERE revision_id = :r"),
                {"r": rev_id},
            )
        ).all()
        shares = (
            await session.execute(
                text(
                    "SELECT user_id, owed_minor, input_value FROM expense_shares "
                    "WHERE revision_id = :r"
                ),
                {"r": rev_id},
            )
        ).all()
        assert sum(a for _, a in payers) == amount
        assert sum(o for _, o, _ in shares) == amount
        recomputed = compute_split(
            SplitRequest(
                total=amount,
                currency=currency,
                payers=tuple(Payer(str(u), a) for u, a in payers),
                mode=SplitMode(mode),
                inputs=tuple(ShareInput(str(u), v) for u, _, v in shares),
            )
        )
        assert {s.id: s.owed for s in recomputed.shares} == {str(u): o for u, o, _ in shares}

    # Revision numbers are 1..n and the expense points at the newest; state matches model.
    service = ExpenseService(session)
    for exp in model:
        assert by_expense[exp.id] == list(range(1, exp.rev_no + 1))
        row = (
            await session.execute(
                select(text("r.rev_no"))
                .select_from(
                    text("expenses e JOIN expense_revisions r ON r.id = e.current_revision_id")
                )
                .where(text("e.id = :id"))
                .params(id=exp.id)
            )
        ).scalar_one()
        assert row == exp.rev_no
        some_member = users[min(exp.people)]
        view = await service.get(some_member, exp.id)
        assert view.current.revision.amount_minor == exp.amount
        assert (view.expense.deleted_at is not None) == exp.deleted
        assert {index[u] for u in view.current.people()} == exp.people

    await _check_balances(session, users)


async def _check_balances(session: AsyncSession, users: list[User]) -> None:
    table = await balance_repo.all_nonzero(session)
    assert table == await expected_from_ledger(session)

    # Each person's balances, from their side, add up to their net position per currency.
    from_balances: dict[tuple[uuid.UUID, str], int] = {}
    for key, amount in table.items():  # positive: b owes a
        a, b = key.party_a, key.party_b
        from_balances[(a, key.currency)] = from_balances.get((a, key.currency), 0) + amount
        from_balances[(b, key.currency)] = from_balances.get((b, key.currency), 0) - amount
    nets = (
        await session.execute(
            text(
                "SELECT who, currency, sum(amount) FROM ("
                "  SELECT p.user_id who, r.currency, p.amount_minor amount"
                "  FROM expenses e JOIN expense_revisions r ON r.id = e.current_revision_id"
                "  JOIN expense_payers p ON p.revision_id = r.id WHERE e.deleted_at IS NULL"
                "  UNION ALL"
                "  SELECT s.user_id, r.currency, -s.owed_minor"
                "  FROM expenses e JOIN expense_revisions r ON r.id = e.current_revision_id"
                "  JOIN expense_shares s ON s.revision_id = r.id WHERE e.deleted_at IS NULL"
                ") x GROUP BY who, currency"
            )
        )
    ).all()
    from_ledger = {(who, cur): int(total) for who, cur, total in nets if total}
    assert {k: v for k, v in from_balances.items() if v} == from_ledger


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(operations())
def test_ledger_stays_consistent(migrated_database: None, ops: list[tuple]) -> None:
    asyncio.run(_run(ops))
