"""Expenses inside a group (PRD section 9; decisions of 2026-11-17 and 2026-11-18)."""

import pytest

from tests.support.api import Api
from tests.support.groups import make_group
from tests.support.people import Person, befriend, equal_split, owed, person

ADITI, BEN, CHEN, DEV = "+6591111111", "+6592222222", "+6593333333", "+6594444444"


@pytest.fixture
async def bali(api: Api) -> tuple[Person, Person, Person, Person, dict]:
    """Aditi, Ben and Chen are in Bali 2027 (so all friends). Dev is Aditi's friend but not
    in the group."""
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    dev = await person(api, DEV, "Dev")
    for p in (ben, chen, dev):
        await befriend(api, aditi, p)
    g = await make_group(api, aditi, [ben, chen])
    return aditi, ben, chen, dev, g


def in_group(g: dict, body: dict) -> dict:
    return {**body, "group_id": g["id"]}


async def create(api: Api, who: Person, body: dict):
    return await api.client.post("/v1/expenses", json=body, headers=who.write())


async def edit(api: Api, who: Person, expense_id: str, body: dict):
    return await api.client.put(f"/v1/expenses/{expense_id}", json=body, headers=who.write())


async def test_any_member_logs_an_expense_they_are_not_on(api: Api, bali) -> None:
    """Aditi, the organiser, logs the hotel Ben paid and shared with Chen."""
    aditi, ben, chen, _, g = bali
    r = await create(api, aditi, in_group(g, equal_split(ben, [ben, chen], 20000)))
    assert r.status_code == 201, r.text
    e = r.json()
    assert (e["context_type"], e["group_id"]) == ("group", g["id"])
    assert owed(e) == {"Ben": 10000, "Chen": 10000}
    assert e["created_by"] == aditi.id


async def test_everyone_must_be_a_member(api: Api, bali) -> None:
    aditi, _, _, dev, g = bali
    r = await create(api, aditi, in_group(g, equal_split(aditi, [aditi, dev], 1000)))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/not-members")
    assert r.json()["errors"] == [{"user_id": dev.id}]


async def test_non_members_cannot_add_or_see(api: Api, bali) -> None:
    aditi, ben, _, dev, g = bali
    r = await create(api, dev, in_group(g, equal_split(dev, [dev], 1000)))
    assert r.status_code == 404
    e = (await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))).json()
    assert (await api.client.get(f"/v1/expenses/{e['id']}", headers=dev.auth)).status_code == 404
    r = await api.client.get("/v1/expenses", headers=dev.auth, params={"group_id": g["id"]})
    assert r.status_code == 404


async def test_any_member_sees_edits_deletes_and_restores(api: Api, bali) -> None:
    aditi, ben, chen, _, g = bali
    e = (await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))).json()
    # Chen isn't on it, but is in the group.
    assert (await api.client.get(f"/v1/expenses/{e['id']}", headers=chen.auth)).status_code == 200
    r = await edit(api, chen, e["id"], in_group(g, equal_split(aditi, [aditi, ben], 3000)))
    assert r.status_code == 200, r.text
    assert r.json()["updated_by"] == chen.id
    assert (
        await api.client.delete(f"/v1/expenses/{e['id']}", headers=chen.write())
    ).status_code == 204
    r = await api.client.post(f"/v1/expenses/{e['id']}/restore", headers=chen.write())
    assert r.status_code == 200


async def test_edit_cannot_change_the_group(api: Api, bali) -> None:
    aditi, ben, _, _, g = bali
    e = (await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))).json()
    r = await edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben], 1000))  # no group_id
    assert r.status_code == 409
    assert r.json()["type"].endswith("/use-move")
    d = (await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))).json()
    r = await edit(api, aditi, d["id"], in_group(g, equal_split(aditi, [aditi, ben], 1000)))
    assert r.json()["type"].endswith("/use-move")


async def test_new_people_in_an_edit_must_be_members(api: Api, bali) -> None:
    aditi, ben, _, dev, g = bali
    e = (await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))).json()
    r = await edit(api, aditi, e["id"], in_group(g, equal_split(aditi, [aditi, ben, dev], 900)))
    assert r.json()["type"].endswith("/not-members")


async def test_expenses_with_someone_who_left_are_locked(api: Api, bali) -> None:
    """Ben settled up and left. The old dinner he was on can't be changed."""
    aditi, ben, chen, _, g = bali
    e = (await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))).json()
    # Settle so Ben can leave: Ben pays Aditi S$5 inside the group.
    r = await api.client.post(
        "/v1/settlements",
        json={"payer_id": ben.id, "receiver_id": aditi.id, "amount_minor": 500,
              "currency": "SGD", "expense_date": "2026-11-18", "group_id": g["id"]},
        headers=ben.write(),
    )  # fmt: skip
    assert r.status_code == 201, r.text
    assert (
        await api.client.delete(f"/v1/groups/{g['id']}/members/{ben.id}", headers=ben.write())
    ).status_code == 204

    for attempt in (
        edit(api, aditi, e["id"], in_group(g, equal_split(aditi, [aditi, chen], 1000))),
        api.client.delete(f"/v1/expenses/{e['id']}", headers=aditi.write()),
    ):
        r = await attempt
        assert r.status_code == 409
        assert r.json()["type"].endswith("/former-member")
        assert "Ben left this group" in r.json()["detail"]
    # Ben can still see it (he was on it) but can't change it.
    assert (await api.client.get(f"/v1/expenses/{e['id']}", headers=ben.auth)).status_code == 200
    r = await edit(api, ben, e["id"], in_group(g, equal_split(ben, [ben], 1000)))
    assert r.status_code == 403
    # Add him back and it can be edited again.
    await api.client.post(
        f"/v1/groups/{g['id']}/members", json={"user_ids": [ben.id]}, headers=aditi.write()
    )
    r = await edit(api, aditi, e["id"], in_group(g, equal_split(aditi, [aditi, ben], 2000)))
    assert r.status_code == 200


async def test_archived_group_is_read_only(api: Api, bali) -> None:
    aditi, ben, _, _, g = bali
    e = (await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))).json()
    await api.client.post(f"/v1/groups/{g['id']}/archive", headers=aditi.write())
    r = await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000)))
    assert r.json()["type"].endswith("/group-archived")
    r = await edit(api, aditi, e["id"], in_group(g, equal_split(aditi, [aditi, ben], 2000)))
    assert r.json()["type"].endswith("/group-archived")
    assert (await api.client.get(f"/v1/expenses/{e['id']}", headers=ben.auth)).status_code == 200


async def test_group_feed_shows_everything_in_the_group(api: Api, bali) -> None:
    aditi, ben, chen, _, g = bali
    await create(api, aditi, in_group(g, equal_split(aditi, [aditi, ben], 1000, name="Dinner")))
    await create(api, ben, in_group(g, equal_split(ben, [ben], 500, name="Ben's snack")))
    await create(api, aditi, equal_split(aditi, [aditi, chen], 700, name="Outside the group"))
    feed = await api.client.get("/v1/expenses", headers=chen.auth, params={"group_id": g["id"]})
    assert sorted(e["name"] for e in feed.json()["items"]) == ["Ben's snack", "Dinner"]
    only_ben = await api.client.get(
        "/v1/expenses", headers=chen.auth, params={"group_id": g["id"], "friend_id": aditi.id}
    )
    assert [e["name"] for e in only_ben.json()["items"]] == ["Dinner"]
    # Chen's own feed (no group filter) lists only expenses he's on.
    mine = (await api.client.get("/v1/expenses", headers=chen.auth)).json()["items"]
    assert [e["name"] for e in mine] == ["Outside the group"]
