"""Editing, deleting, restoring and the history of an expense (PRD section 7)."""

import asyncio

import pytest

from tests.support.api import Api
from tests.support.people import Person, befriend, equal_split, owed, person

ADITI, BEN, CHEN, DEV = "+6591111111", "+6592222222", "+6593333333", "+6594444444"


@pytest.fixture
async def trio(api: Api) -> tuple[Person, Person, Person]:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    await befriend(api, aditi, ben)
    await befriend(api, aditi, chen)
    return aditi, ben, chen


async def create(api: Api, who: Person, body: dict) -> dict:
    r = await api.client.post("/v1/expenses", json=body, headers=who.write())
    assert r.status_code == 201, r.text
    return r.json()


async def edit(api: Api, who: Person, expense_id: str, body: dict):
    return await api.client.put(f"/v1/expenses/{expense_id}", json=body, headers=who.write())


# --- Editing ------------------------------------------------------------------------------


async def test_edit_adds_a_revision_and_keeps_the_old_one(api: Api, trio) -> None:
    aditi, ben, chen = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben, chen], 900))
    r = await edit(api, ben, e["id"], equal_split(aditi, [aditi, ben, chen], 1200, name="Brunch"))
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["rev_no"] == 2
    assert new["name"] == "Brunch"
    assert owed(new) == {"Aditi": 400, "Ben": 400, "Chen": 400}
    assert new["created_by"] == aditi.id
    assert new["updated_by"] == ben.id

    history = (await api.client.get(f"/v1/expenses/{e['id']}/revisions", headers=chen.auth)).json()
    revs = history["items"]
    assert [(h["rev_no"], h["reason"], h["name"]) for h in revs] == [
        (1, "create", "Dinner"),
        (2, "edit", "Brunch"),
    ]
    assert owed(revs[0]) == {"Aditi": 300, "Ben": 300, "Chen": 300}  # untouched
    assert revs[1]["created_by"] == ben.id


async def test_last_save_wins_and_nothing_is_lost(api: Api, trio) -> None:
    """Aditi and Ben both open the S$10 expense. Ben saves S$20, then Aditi saves S$30
    from her older screen. Her save goes through without a reload; Ben's stays in history."""
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    assert (
        await edit(api, ben, e["id"], equal_split(aditi, [aditi, ben], 2000))
    ).status_code == 200
    r = await edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben], 3000))
    assert r.status_code == 200
    assert r.json()["amount_minor"] == 3000
    assert r.json()["rev_no"] == 3
    now = (await api.client.get(f"/v1/expenses/{e['id']}", headers=ben.auth)).json()
    assert now["amount_minor"] == 3000
    history = (await api.client.get(f"/v1/expenses/{e['id']}/revisions", headers=ben.auth)).json()
    assert [(h["amount_minor"], h["created_by"]) for h in history["items"]] == [
        (1000, aditi.id),
        (2000, ben.id),
        (3000, aditi.id),
    ]


async def test_saves_at_the_same_moment_both_land_in_order(api: Api, trio) -> None:
    """Two saves at once queue up (row lock): no crash, no lost version."""
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    results = await asyncio.gather(
        edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben], 2000)),
        edit(api, ben, e["id"], equal_split(aditi, [aditi, ben], 3000)),
    )
    assert [r.status_code for r in results] == [200, 200]
    history = (await api.client.get(f"/v1/expenses/{e['id']}/revisions", headers=ben.auth)).json()
    assert [h["rev_no"] for h in history["items"]] == [1, 2, 3]
    assert sorted(h["amount_minor"] for h in history["items"][1:]) == [2000, 3000]


async def test_edit_is_validated_like_create(api: Api, trio) -> None:
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    bad = equal_split(aditi, [aditi, ben], 1000)
    bad["payers"][0]["amount_minor"] = 1
    r = await edit(api, aditi, e["id"], bad)
    assert r.json()["type"].endswith("/sum-mismatch")
    r = await edit(api, aditi, e["id"], equal_split(ben, [ben], 1000))
    assert r.json()["type"].endswith("/not-involved")


async def test_new_people_in_an_edit_must_be_the_editors_friends(api: Api, trio) -> None:
    aditi, ben, chen = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    # Ben isn't friends with Chen, so Ben can't add Chen...
    r = await edit(api, ben, e["id"], equal_split(ben, [aditi, ben, chen], 900))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/not-friends")
    # ...but Aditi can, and then Ben and Chen become friends through the expense.
    r = await edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben, chen], 900))
    assert r.status_code == 200
    friends = (await api.client.get("/v1/friends", headers=ben.auth)).json()["items"]
    assert {f["display_name"]: f["source"] for f in friends}["Chen"] == "expense"


async def test_existing_people_stay_even_if_no_longer_friends(api: Api, trio) -> None:
    """Money facts aren't hidden: unfriending doesn't block editing a shared expense."""
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    await api.client.delete(f"/v1/friends/{ben.id}", headers=aditi.write())
    r = await edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben], 1500))
    assert r.status_code == 200
    # And editing doesn't quietly re-friend them.
    friends = (await api.client.get("/v1/friends", headers=aditi.auth)).json()["items"]
    assert "Ben" not in [f["display_name"] for f in friends]


async def test_removed_person_can_view_but_not_change(api: Api, trio) -> None:
    aditi, ben, chen = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben, chen], 900))
    assert (
        await edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben], 900))
    ).status_code == 200
    r = await api.client.get(f"/v1/expenses/{e['id']}", headers=chen.auth)
    assert r.status_code == 200  # Chen can still see why he's no longer on it
    r = await api.client.get(f"/v1/expenses/{e['id']}/revisions", headers=chen.auth)
    assert len(r.json()["items"]) == 2
    r = await edit(api, chen, e["id"], equal_split(chen, [chen], 900))
    assert r.status_code == 403
    r = await api.client.delete(f"/v1/expenses/{e['id']}", headers=chen.write())
    assert r.status_code == 403
    # Chen's feed no longer lists it.
    assert (await api.client.get("/v1/expenses", headers=chen.auth)).json()["items"] == []


async def test_outsider_cannot_edit_or_see_history(api: Api, trio) -> None:
    aditi, ben, _ = trio
    dev = await person(api, DEV, "Dev")
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    assert (await edit(api, dev, e["id"], equal_split(dev, [dev], 1000))).status_code == 404
    r = await api.client.get(f"/v1/expenses/{e['id']}/revisions", headers=dev.auth)
    assert r.status_code == 404
    assert (
        await api.client.delete(f"/v1/expenses/{e['id']}", headers=dev.write())
    ).status_code == 404


# --- Delete and restore -------------------------------------------------------------------


async def test_any_participant_can_delete_and_restore(api: Api, trio) -> None:
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    assert (
        await api.client.delete(f"/v1/expenses/{e['id']}", headers=ben.write())
    ).status_code == 204
    gone = (await api.client.get(f"/v1/expenses/{e['id']}", headers=aditi.auth)).json()
    assert gone["deleted_by"] == ben.id
    assert gone["deleted_at"] is not None

    # Deleting again is harmless.
    assert (
        await api.client.delete(f"/v1/expenses/{e['id']}", headers=aditi.write())
    ).status_code == 204
    assert (await api.client.get(f"/v1/expenses/{e['id']}", headers=aditi.auth)).json()[
        "deleted_by"
    ] == ben.id

    # Can't edit while deleted.
    r = await edit(api, aditi, e["id"], equal_split(aditi, [aditi, ben], 2000))
    assert r.status_code == 409
    assert r.json()["type"].endswith("/expense-deleted")

    r = await api.client.post(f"/v1/expenses/{e['id']}/restore", headers=aditi.write())
    assert r.status_code == 200
    assert r.json()["deleted_at"] is None
    assert r.json()["deleted_by"] is None
    assert r.json() == {**e, "updated_at": r.json()["updated_at"]}  # same as before


async def test_restore_window_is_30_days(api: Api, trio, db_execute) -> None:
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    await api.client.delete(f"/v1/expenses/{e['id']}", headers=aditi.write())
    await db_execute(
        "UPDATE expenses SET deleted_at = now() - interval '31 days' WHERE id = :id", id=e["id"]
    )
    r = await api.client.post(f"/v1/expenses/{e['id']}/restore", headers=aditi.write())
    assert r.status_code == 409
    assert r.json()["type"].endswith("/restore-window-passed")
    # And it's no longer offered in the deleted list.
    deleted = await api.client.get("/v1/expenses", headers=aditi.auth, params={"status": "deleted"})
    assert deleted.json()["items"] == []


async def test_history_is_never_rewritten_in_the_database(api: Api, trio, db_execute) -> None:
    """Belt and braces: even raw SQL can't change a saved revision (append-only trigger)."""
    aditi, ben, _ = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    with pytest.raises(Exception, match="append-only"):
        await db_execute(
            "UPDATE expense_shares SET owed_minor = 0 WHERE revision_id = "
            "(SELECT current_revision_id FROM expenses WHERE id = :id)",
            id=e["id"],
        )
