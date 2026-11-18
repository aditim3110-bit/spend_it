"""Creating, viewing, changing and archiving groups (PRD section 9)."""

import pytest

from tests.support.api import Api
from tests.support.groups import make_group, member_names
from tests.support.people import Person, befriend, person

ADITI, BEN, CHEN, DEV = "+6591111111", "+6592222222", "+6593333333", "+6594444444"


@pytest.fixture
async def trio(api: Api) -> tuple[Person, Person, Person]:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    await befriend(api, aditi, ben)
    await befriend(api, aditi, chen)
    return aditi, ben, chen


async def test_create_with_friends(api: Api, trio) -> None:
    aditi, ben, chen = trio
    g = await make_group(api, aditi, [ben, chen])
    assert g["name"] == "Bali 2027"
    assert g["type"] == "trip"
    assert g["smart_settle"] is True  # on by default
    assert member_names(g) == ["Aditi", "Ben", "Chen"]  # creator first
    assert "role" not in g["members"][0]  # everyone is equal: no admins


async def test_everyone_in_a_group_becomes_friends(api: Api, trio) -> None:
    aditi, ben, chen = trio
    await make_group(api, aditi, [ben, chen])
    friends = (await api.client.get("/v1/friends", headers=ben.auth)).json()["items"]
    assert {f["display_name"]: f["source"] for f in friends} == {
        "Aditi": "phone_email",
        "Chen": "group",
    }


async def test_only_friends_can_be_added_at_creation(api: Api, trio) -> None:
    aditi, _, _ = trio
    dev = await person(api, DEV, "Dev")
    r = await api.client.post(
        "/v1/groups",
        json={"name": "X", "type": "home", "default_currency": "SGD", "member_ids": [dev.id]},
        headers=aditi.write(),
    )
    assert r.status_code == 422
    assert r.json()["type"].endswith("/not-friends")


async def test_validation(api: Api, trio) -> None:
    aditi, _, _ = trio
    base = {"name": "Flat", "type": "home", "default_currency": "SGD"}
    for bad in ({"name": "  "}, {"type": "party"}, {"default_currency": "XXX"}, {"extra": 1}):
        r = await api.client.post("/v1/groups", json=base | bad, headers=aditi.write())
        assert r.status_code == 422, bad


async def test_outsiders_cannot_see_a_group(api: Api, trio) -> None:
    aditi, ben, _ = trio
    dev = await person(api, DEV, "Dev")
    g = await make_group(api, aditi, [ben])
    assert (await api.client.get(f"/v1/groups/{g['id']}", headers=ben.auth)).status_code == 200
    assert (await api.client.get(f"/v1/groups/{g['id']}", headers=dev.auth)).status_code == 404


async def test_list_my_groups_newest_first_with_pages(api: Api, trio) -> None:
    aditi, ben, chen = trio
    for name in ("One", "Two", "Three"):
        await make_group(api, aditi, [ben], name=name)
    await make_group(api, chen, [], name="Chen's own")
    r = await api.client.get("/v1/groups", headers=aditi.auth, params={"limit": 2})
    page = r.json()
    assert [g["name"] for g in page["items"]] == ["Three", "Two"]
    assert page["items"][0]["member_count"] == 2
    r = await api.client.get(
        "/v1/groups", headers=aditi.auth, params={"limit": 2, "cursor": page["next_cursor"]}
    )
    assert [g["name"] for g in r.json()["items"]] == ["One"]
    assert r.json()["next_cursor"] is None
    ben_groups = (await api.client.get("/v1/groups", headers=ben.auth)).json()["items"]
    assert len(ben_groups) == 3


async def test_any_member_changes_settings(api: Api, trio) -> None:
    aditi, ben, _ = trio
    g = await make_group(api, aditi, [ben])
    url = f"/v1/groups/{g['id']}"
    r = await api.client.patch(
        url,
        json={"smart_settle": False, "name": "Bali!", "default_currency": "IDR"},
        headers=ben.write(),  # Ben didn't create the group
    )
    assert r.status_code == 200
    assert (r.json()["smart_settle"], r.json()["name"], r.json()["default_currency"]) == (
        False, "Bali!", "IDR",
    )  # fmt: skip


async def test_archive_makes_it_read_only_and_hidden(api: Api, trio) -> None:
    aditi, ben, chen = trio
    g = await make_group(api, aditi, [ben])
    url = f"/v1/groups/{g['id']}"
    r = await api.client.post(f"{url}/archive", headers=ben.write())  # any member
    assert r.status_code == 200
    assert r.json()["archived_at"] is not None

    assert (await api.client.get("/v1/groups", headers=ben.auth)).json()["items"] == []
    archived = await api.client.get("/v1/groups", headers=ben.auth, params={"archived": True})
    assert [x["name"] for x in archived.json()["items"]] == ["Bali 2027"]

    for attempt in (
        api.client.patch(url, json={"name": "New"}, headers=aditi.write()),
        api.client.post(f"{url}/members", json={"user_ids": [chen.id]}, headers=aditi.write()),
        api.client.post(f"{url}/invites", json={}, headers=aditi.write()),
    ):
        r = await attempt
        assert r.status_code == 409
        assert r.json()["type"].endswith("/group-archived")

    r = await api.client.post(f"{url}/unarchive", headers=aditi.write())
    assert r.json()["archived_at"] is None
    assert (
        await api.client.patch(url, json={"name": "New"}, headers=aditi.write())
    ).status_code == 200
