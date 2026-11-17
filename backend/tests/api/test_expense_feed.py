"""The expense list: GET /v1/expenses (PRD section 17)."""

import pytest

from tests.support.api import Api
from tests.support.people import Person, befriend, equal_split, person

ADITI, BEN, CHEN = "+6591111111", "+6592222222", "+6593333333"


@pytest.fixture
async def trio(api: Api) -> tuple[Person, Person, Person]:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    await befriend(api, aditi, ben)
    await befriend(api, aditi, chen)
    return aditi, ben, chen


async def add(api: Api, who: Person, people: list[Person], name: str, day: str) -> str:
    body = equal_split(who, people, 1000, name=name, expense_date=day)
    r = await api.client.post("/v1/expenses", json=body, headers=who.write())
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def names(api: Api, who: Person, **params) -> list[str]:
    r = await api.client.get("/v1/expenses", headers=who.auth, params=params)
    assert r.status_code == 200, r.text
    return [e["name"] for e in r.json()["items"]]


async def test_newest_expense_date_first_and_only_mine(api: Api, trio) -> None:
    aditi, ben, chen = trio
    await add(api, aditi, [aditi, ben], "Lunch", "2026-11-10")
    await add(api, aditi, [aditi, chen], "Taxi", "2026-11-15")
    await add(api, aditi, [aditi, ben], "Old one, entered late", "2026-11-01")
    assert await names(api, aditi) == ["Taxi", "Lunch", "Old one, entered late"]
    assert await names(api, ben) == ["Lunch", "Old one, entered late"]
    assert await names(api, chen) == ["Taxi"]


async def test_filter_by_friend(api: Api, trio) -> None:
    aditi, ben, chen = trio
    await add(api, aditi, [aditi, ben], "With Ben", "2026-11-10")
    await add(api, aditi, [aditi, chen], "With Chen", "2026-11-11")
    await add(api, aditi, [aditi, ben, chen], "All three", "2026-11-12")
    assert await names(api, aditi, friend_id=ben.id) == ["All three", "With Ben"]
    assert await names(api, aditi, friend_id=chen.id) == ["All three", "With Chen"]


async def test_pages_cover_everything_once(api: Api, trio) -> None:
    aditi, ben, _ = trio
    added = [await add(api, aditi, [aditi, ben], f"E{i}", "2026-11-17") for i in range(7)]
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        page = (await api.client.get("/v1/expenses", headers=aditi.auth, params=params)).json()
        seen += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(added)
    assert len(seen) == len(set(seen))


async def test_bad_cursor_is_a_clear_error(api: Api, trio) -> None:
    aditi, _, _ = trio
    r = await api.client.get("/v1/expenses", headers=aditi.auth, params={"cursor": "nonsense"})
    assert r.status_code == 422
    assert r.json()["type"].endswith("/invalid-cursor")


async def test_deleted_expenses_move_to_the_deleted_list(api: Api, trio) -> None:
    aditi, ben, _ = trio
    keep = await add(api, aditi, [aditi, ben], "Keep", "2026-11-10")
    gone = await add(api, aditi, [aditi, ben], "Gone", "2026-11-11")
    assert keep
    r = await api.client.delete(f"/v1/expenses/{gone}", headers=ben.write())
    assert r.status_code == 204
    assert await names(api, aditi) == ["Keep"]
    assert await names(api, aditi, status="deleted") == ["Gone"]
