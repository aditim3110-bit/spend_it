"""Property test for group membership (PRD section 9; decisions of 2026-11-17).

Hypothesis invents random sequences of: add a friend, leave, remove someone, change a
join by link, unfriend, and "money is now owed between two members". Each runs
through the real GroupService and Postgres and is compared with a small in-memory model
of what should happen. After every sequence we check:

- each step succeeded exactly when the rules say it should;
- nobody is in the group twice, and members are listed in the order they joined;
- the friendships in the database are exactly what the model expects (joining makes you
  friends with everyone there; unfriending is respected; nobody is re-friended later);
- nobody left or was removed while money was open for them in the group.

Each sequence runs inside a transaction that is rolled back.
"""

import asyncio
import uuid
from itertools import combinations

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import ProblemError
from app.models import Friendship, FriendSource, GroupMember, User
from app.models.expense import ContextType
from app.models.group import GroupType
from app.repositories import balances as balance_repo
from app.repositories import friends as friend_repo
from app.repositories.balances import Key
from app.schemas.groups import GroupCreateIn
from app.services.groups import GroupService
from app.services.simplify import simplify
from tests.support.database import TEST_DATABASE_URL

PEOPLE = 5
person = st.integers(0, PEOPLE - 1)
owe = st.tuples(st.just("owe"), person, person, st.sampled_from([0, 500, 500]))
leave = st.tuples(st.just("leave"), person)
remove = st.tuples(st.just("remove"), person, person)
# "owe", "leave" and "remove" appear more often, so the "settle up first" rule gets tested.
operation = st.one_of(
    st.tuples(st.just("add"), person, person),
    leave,
    leave,
    remove,
    remove,
    st.tuples(st.just("join"), person),
    st.tuples(st.just("unfriend"), person, person),
    owe,
    owe,
    owe,
)
# Who starts as friends: person 0 (who creates the group) is friends with everyone, and
# the friendships among the others are random, so "only add your friends" still bites.
pairs = list(combinations(range(1, PEOPLE), 2))
CREATOR_FRIENDS = [(0, i) for i in range(1, PEOPLE)]


class Model:
    def __init__(self, friends: set[frozenset[int]]) -> None:
        self.members: list[int] = [0]  # in join order; everyone is equal
        self.friends = set(friends)
        # (a, b) with a's user ID < b's, as stored: a positive amount means b owes a.
        self.owed: dict[tuple[int, int], int] = {}

    def has_money_open(self, who: int) -> bool:
        """Is `who` on the group's settle-up list? Smart Settle is on in this test, so
        that's the Smart Settle payments (which depend on who is friends)."""
        plain = {(str(b), str(a)): amt for (a, b), amt in self.owed.items() if amt}
        nets: dict[str, int] = {}
        for (debtor, creditor), amt in plain.items():
            nets[debtor] = nets.get(debtor, 0) - amt
            nets[creditor] = nets.get(creditor, 0) + amt
        payments = simplify(nets, plain, lambda x, y: frozenset((int(x), int(y))) in self.friends)
        return any(str(who) in pair for pair in payments)

    def join(self, who: int) -> None:
        for other in self.members:
            self.friends.add(frozenset((who, other)))
        self.members.append(who)

    def drop(self, who: int) -> None:
        self.members.remove(who)


async def _scenario(
    session: AsyncSession, friend_pairs: list[tuple[int, int]], start: list[int], ops
) -> None:
    users = [User(id=uuid.uuid4(), display_name=f"P{i}") for i in range(PEOPLE)]
    session.add_all(users)
    await session.flush()
    await friend_repo.connect_many(
        session,
        {(users[a].id, users[b].id) for a, b in [*CREATOR_FRIENDS, *friend_pairs]},
        FriendSource.QR,
    )
    await session.commit()
    index = {u.id: i for i, u in enumerate(users)}

    service = GroupService(session)
    friend_pairs = [*CREATOR_FRIENDS, *friend_pairs]
    model = Model({frozenset(p) for p in friend_pairs})
    # The group starts with person 0 and the people listed in `start`.
    founders = list(start)
    detail = await service.create(
        users[0],
        GroupCreateIn(
            name="G",
            type=GroupType.TRIP,
            default_currency="SGD",
            member_ids=[users[i].id for i in founders],
        ),
    )
    group_id = detail.group.id
    for i in founders:
        model.join(i)

    for op in ops:
        kind, actor = op[0], op[1]
        expected_ok: bool
        try:
            if kind == "add":
                target = op[2]
                expected_ok = (
                    actor in model.members
                    and target not in model.members
                    and frozenset((actor, target)) in model.friends
                )
                await service.add_members(users[actor], group_id, [users[target].id])
                model.join(target)
            elif kind == "leave":
                expected_ok = actor in model.members and not model.has_money_open(actor)
                await service.remove(users[actor], group_id, users[actor].id)
                model.drop(actor)
            elif kind == "remove":
                target = op[2]
                if target == actor:
                    continue  # that's "leave"
                expected_ok = (
                    actor in model.members
                    and target in model.members
                    and not model.has_money_open(target)
                )
                await service.remove(users[actor], group_id, users[target].id)
                model.drop(target)
            elif kind == "join":
                if not model.members:
                    continue  # nobody left to make a link
                inviter = model.members[0]
                invite = await service.create_invite(users[inviter], group_id, False)
                result = await service.accept(users[actor], invite.token)
                expected_ok = True
                assert result.status == ("already_member" if actor in model.members else "joined")
                if result.status == "joined":
                    model.join(actor)
            elif kind == "unfriend":
                other = op[2]
                if other == actor:
                    continue
                expected_ok = True
                await friend_repo.remove(session, users[actor].id, users[other].id)
                await session.commit()
                model.friends.discard(frozenset((actor, other)))
            else:  # owe: set the group balance between two current members
                other, amount = op[2], op[3]
                if other == actor or actor not in model.members or other not in model.members:
                    continue
                expected_ok = True
                ia, ib = sorted((actor, other), key=lambda i: users[i].id)
                key = Key(ContextType.GROUP, group_id, users[ia].id, users[ib].id, "SGD")
                await balance_repo.apply(session, {key: amount - model.owed.get((ia, ib), 0)})
                await session.commit()
                model.owed[(ia, ib)] = amount
                if amount and model.has_money_open(actor):
                    # They're on the settle-up list: leaving must be refused right away.
                    try:
                        await service.remove(users[actor], group_id, users[actor].id)
                    except ProblemError as err:
                        assert err.slug == "balance-not-zero", err.detail
                        event("refused: money still open")
                    else:
                        raise AssertionError(("left with money open", op))
            assert expected_ok, ("succeeded but should have been refused", op)
        except ProblemError as err:
            assert not expected_ok, ("refused but should have succeeded", op, err.detail)
            if err.slug == "balance-not-zero":
                event("refused: money still open")

    # The database agrees with the model.
    rows = (
        (
            await session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group_id, GroupMember.left_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    current = [index[m.user_id] for m in rows]
    assert len(current) == len(set(current))  # nobody in twice
    by_join = sorted(rows, key=lambda m: m.joined_at)
    assert [index[m.user_id] for m in by_join] == model.members

    ids = list(index)
    friendships = (
        await session.execute(
            select(Friendship.user_a, Friendship.user_b).where(Friendship.user_a.in_(ids))
        )
    ).all()
    assert {frozenset((index[a], index[b])) for a, b in friendships} == model.friends


async def _run(friend_pairs, start, ops) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            await _scenario(session, friend_pairs, start, ops)
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    friend_pairs=st.lists(st.sampled_from(pairs), unique=True, max_size=len(pairs)),
    start=st.lists(st.integers(1, PEOPLE - 1), unique=True, min_size=1),
    ops=st.lists(operation, min_size=1, max_size=15),
)
def test_membership_rules_always_hold(migrated_database: None, friend_pairs, start, ops) -> None:
    asyncio.run(_run(friend_pairs, start, ops))
