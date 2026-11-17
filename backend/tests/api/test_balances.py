"""Balances: who owes whom (PRD section 8)."""

import uuid

import pytest

from tests.support.api import Api
from tests.support.people import Person, befriend, equal_split, person

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


async def balances(api: Api, who: Person) -> dict:
    r = await api.client.get("/v1/balances", headers=who.auth)
    assert r.status_code == 200, r.text
    return r.json()


def lines(b: dict) -> dict[str, dict[str, int]]:
    """{name: {currency: amount}} where positive means they owe you."""
    return {
        p["display_name"]: {a["currency"]: a["amount_minor"] for a in p["amounts"]}
        for p in b["people"]
    }


def totals(b: dict) -> dict[str, tuple[int, int]]:
    return {t["currency"]: (t["owed_to_you"], t["you_owe"]) for t in b["totals"]}


async def test_nothing_shared_means_empty(api: Api, trio) -> None:
    aditi, _, _ = trio
    assert await balances(api, aditi) == {"totals": [], "people": []}


async def test_one_payer_everyone_owes_their_share(api: Api, trio) -> None:
    aditi, ben, chen = trio
    await create(api, aditi, equal_split(aditi, [aditi, ben, chen], 10000))
    a = await balances(api, aditi)
    assert lines(a) == {"Ben": {"SGD": 3333}, "Chen": {"SGD": 3333}}
    assert totals(a) == {"SGD": (6666, 0)}
    b = await balances(api, ben)
    assert lines(b) == {"Aditi": {"SGD": -3333}}  # Ben owes Aditi
    assert totals(b) == {"SGD": (0, 3333)}
    # Ben and Chen share the dinner but owe each other nothing.
    assert "Chen" not in lines(b)


async def test_hotel_with_two_payers(api: Api, trio) -> None:
    """S$300 three ways; Aditi paid 200, Ben 100. Only Chen owes, and he owes Aditi."""
    aditi, ben, chen = trio
    body = equal_split(aditi, [aditi, ben, chen], 30000)
    body["payers"] = [
        {"user_id": aditi.id, "amount_minor": 20000},
        {"user_id": ben.id, "amount_minor": 10000},
    ]
    await create(api, aditi, body)
    assert lines(await balances(api, aditi)) == {"Chen": {"SGD": 10000}}
    assert lines(await balances(api, ben)) == {}
    assert lines(await balances(api, chen)) == {"Aditi": {"SGD": -10000}}


async def test_expenses_add_up_and_cancel_out(api: Api, trio) -> None:
    aditi, ben, _ = trio
    await create(api, aditi, equal_split(aditi, [aditi, ben], 4000))  # Ben owes 20
    await create(api, ben, equal_split(ben, [aditi, ben], 1000))  # Aditi owes 5
    assert lines(await balances(api, aditi)) == {"Ben": {"SGD": 1500}}
    await create(api, ben, equal_split(ben, [aditi, ben], 3000))  # Aditi owes 15
    assert lines(await balances(api, aditi)) == {}  # square
    assert await balances(api, ben) == {"totals": [], "people": []}


async def test_currencies_are_never_added_together(api: Api, trio) -> None:
    aditi, ben, _ = trio
    await create(api, aditi, equal_split(aditi, [aditi, ben], 2000))
    await create(api, ben, equal_split(ben, [aditi, ben], 1000, currency="THB"))
    await create(api, aditi, equal_split(aditi, [aditi, ben], 1000, currency="JPY"))
    a = await balances(api, aditi)
    assert lines(a) == {"Ben": {"JPY": 500, "SGD": 1000, "THB": -500}}
    assert totals(a) == {"JPY": (500, 0), "SGD": (1000, 0), "THB": (0, 500)}


async def test_edit_delete_and_restore_move_the_balance(api: Api, trio) -> None:
    aditi, ben, chen = trio
    e = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    assert lines(await balances(api, aditi)) == {"Ben": {"SGD": 500}}

    # Edit: now S$30 three ways, Chen included. Ben's old 5 is replaced, not added to.
    r = await api.client.put(
        f"/v1/expenses/{e['id']}",
        json=equal_split(aditi, [aditi, ben, chen], 3000),
        headers=aditi.write(),
    )
    assert r.status_code == 200
    assert lines(await balances(api, aditi)) == {"Ben": {"SGD": 1000}, "Chen": {"SGD": 1000}}

    await api.client.delete(f"/v1/expenses/{e['id']}", headers=ben.write())
    assert lines(await balances(api, aditi)) == {}

    await api.client.post(f"/v1/expenses/{e['id']}/restore", headers=chen.write())
    assert lines(await balances(api, aditi)) == {"Ben": {"SGD": 1000}, "Chen": {"SGD": 1000}}


async def test_unfriending_does_not_hide_money(api: Api, trio) -> None:
    aditi, ben, _ = trio
    await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    await api.client.delete(f"/v1/friends/{ben.id}", headers=aditi.write())
    assert lines(await balances(api, aditi)) == {"Ben": {"SGD": 500}}


async def test_balance_with_one_person(api: Api, trio) -> None:
    aditi, ben, _ = trio
    await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))
    await create(api, aditi, equal_split(aditi, [aditi, ben], 600, currency="JPY"))
    r = await api.client.get(f"/v1/balances/friends/{ben.id}", headers=aditi.auth)
    assert r.status_code == 200
    assert r.json() == {
        "user_id": ben.id,
        "display_name": "Ben",
        "amounts": [
            {"currency": "JPY", "amount_minor": 300},
            {"currency": "SGD", "amount_minor": 500},
        ],
        "contexts": [
            {
                "context_type": "direct",
                "group_id": None,
                "amounts": [
                    {"currency": "JPY", "amount_minor": 300},
                    {"currency": "SGD", "amount_minor": 500},
                ],
            }
        ],
    }
    mirror = (await api.client.get(f"/v1/balances/friends/{aditi.id}", headers=ben.auth)).json()
    assert [a["amount_minor"] for a in mirror["amounts"]] == [-300, -500]


async def test_balance_with_someone_you_share_nothing_with_is_empty(api: Api, trio) -> None:
    aditi, _, _ = trio
    dev = await person(api, DEV, "Dev")
    r = await api.client.get(f"/v1/balances/friends/{dev.id}", headers=aditi.auth)
    assert r.status_code == 200
    assert r.json()["amounts"] == [] and r.json()["contexts"] == []
    for missing in (uuid.uuid4(), aditi.id):  # nobody, or yourself
        r = await api.client.get(f"/v1/balances/friends/{missing}", headers=aditi.auth)
        assert r.status_code == 404
