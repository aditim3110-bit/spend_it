"""Adding, promoting, removing and leaving (PRD section 9; decisions of 2026-11-17)."""

import pytest

from tests.support.api import Api
from tests.support.groups import make_group, member_names
from tests.support.people import Person, befriend, person

ADITI, BEN, CHEN, DEV = "+6591111111", "+6592222222", "+6593333333", "+6594444444"


@pytest.fixture
async def people(api: Api) -> tuple[Person, Person, Person, Person]:
    """Aditi and Ben are friends, Ben and Chen are friends; Dev knows nobody."""
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    dev = await person(api, DEV, "Dev")
    await befriend(api, aditi, ben)
    await befriend(api, ben, chen)
    return aditi, ben, chen, dev


async def add(api: Api, who: Person, group: dict, *new: Person):
    return await api.client.post(
        f"/v1/groups/{group['id']}/members",
        json={"user_ids": [p.id for p in new]},
        headers=who.write(),
    )


async def remove(api: Api, who: Person, group: dict, target: Person):
    return await api.client.delete(
        f"/v1/groups/{group['id']}/members/{target.id}", headers=who.write()
    )


async def detail(api: Api, who: Person, group: dict) -> dict:
    return (await api.client.get(f"/v1/groups/{group['id']}", headers=who.auth)).json()


# --- Adding -------------------------------------------------------------------------------


async def test_any_member_adds_their_own_friends(api: Api, people) -> None:
    aditi, ben, chen, _ = people
    g = await make_group(api, aditi, [ben])
    r = await add(api, ben, g, chen)  # Ben (not the creator) adds his friend Chen
    assert r.status_code == 200, r.text
    assert member_names(r.json()) == ["Aditi", "Ben", "Chen"]
    # Joining made Aditi and Chen friends.
    friends = (await api.client.get("/v1/friends", headers=aditi.auth)).json()["items"]
    assert {f["display_name"]: f["source"] for f in friends}["Chen"] == "group"


async def test_cannot_add_strangers_or_existing_members(api: Api, people) -> None:
    aditi, ben, chen, dev = people
    g = await make_group(api, aditi, [ben])
    r = await add(api, aditi, g, chen)  # Chen isn't Aditi's friend
    assert r.json()["type"].endswith("/not-friends")
    r = await add(api, aditi, g, dev)
    assert r.json()["type"].endswith("/not-friends")
    r = await add(api, aditi, g, ben)
    assert r.json()["type"].endswith("/already-member")


async def test_non_members_cannot_add(api: Api, people) -> None:
    aditi, ben, chen, _ = people
    g = await make_group(api, aditi, [])
    assert (await add(api, ben, g, chen)).status_code == 404


# --- Removing and leaving -----------------------------------------------------------------


async def test_any_member_removes_and_anyone_leaves(api: Api, people) -> None:
    aditi, ben, chen, _ = people
    g = await make_group(api, aditi, [ben])
    await add(api, ben, g, chen)
    assert (await remove(api, ben, g, aditi)).status_code == 204  # even the creator
    assert (await remove(api, chen, g, ben)).status_code == 204
    assert member_names(await detail(api, chen, g)) == ["Chen"]
    assert (await remove(api, chen, g, chen)).status_code == 204  # Chen leaves last


async def test_removed_people_lose_access(api: Api, people) -> None:
    aditi, ben, _, _ = people
    g = await make_group(api, aditi, [ben])
    assert (await remove(api, ben, g, ben)).status_code == 204  # Ben leaves
    assert member_names(await detail(api, aditi, g)) == ["Aditi"]
    # Once out, the group is invisible to them.
    assert (await api.client.get(f"/v1/groups/{g['id']}", headers=ben.auth)).status_code == 404


async def test_cannot_leave_or_be_removed_with_money_open(api: Api, people, db_execute) -> None:
    """Group expenses arrive in Milestone 12; here a group balance is inserted directly."""
    aditi, ben, _, _ = people
    g = await make_group(api, aditi, [ben])
    a, b = sorted([aditi.id, ben.id])
    await db_execute(
        "INSERT INTO balances (context_type, group_id, party_a, party_b, currency, amount_minor)"
        " VALUES ('group', :g, :a, :b, 'SGD', 1500)",
        g=g["id"], a=a, b=b,
    )  # fmt: skip
    for r in (await remove(api, ben, g, ben), await remove(api, aditi, g, ben)):
        assert r.status_code == 409
        assert r.json()["type"].endswith("/balance-not-zero")
        assert r.json()["errors"][0]["currency"] == "SGD"
        assert abs(r.json()["errors"][0]["amount_minor"]) == 1500
    await db_execute("UPDATE balances SET amount_minor = 0 WHERE group_id = :g", g=g["id"])
    assert (await remove(api, ben, g, ben)).status_code == 204


async def test_rejoining_after_leaving_starts_a_new_stint(api: Api, people) -> None:
    aditi, ben, _, _ = people
    g = await make_group(api, aditi, [ben])
    await remove(api, ben, g, ben)
    r = await add(api, aditi, g, ben)
    assert r.status_code == 200
    assert member_names(r.json()) == ["Aditi", "Ben"]
