"""Recording payments: POST/PUT /v1/settlements (PRD section 8)."""

import asyncio
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


async def add_expense(api: Api, who: Person, body: dict) -> dict:
    r = await api.client.post("/v1/expenses", json=body, headers=who.write())
    assert r.status_code == 201, r.text
    return r.json()


def payment(payer: Person, receiver: Person, amount: int, **extra) -> dict:
    return {
        "payer_id": payer.id,
        "receiver_id": receiver.id,
        "amount_minor": amount,
        "currency": "SGD",
        "expense_date": "2026-11-18",
        **extra,
    }


async def pay(api: Api, who: Person, body: dict):
    return await api.client.post("/v1/settlements", json=body, headers=who.write())


async def owes(api: Api, who: Person, other: Person, currency: str = "SGD") -> int:
    """What `who` owes `other` (negative: other owes who)."""
    r = await api.client.get(f"/v1/balances/friends/{other.id}", headers=who.auth)
    amounts = {a["currency"]: a["amount_minor"] for a in r.json()["amounts"]}
    return -amounts.get(currency, 0)


@pytest.fixture
async def dinner(api: Api, trio) -> dict:
    """Aditi paid S$100 for dinner three ways: Ben and Chen each owe her S$33.33."""
    aditi, ben, chen = trio
    return await add_expense(api, aditi, equal_split(aditi, [aditi, ben, chen], 10000))


# --- Recording ----------------------------------------------------------------------------


async def test_payer_records_and_is_square(api: Api, trio, dinner) -> None:
    aditi, ben, _ = trio
    r = await pay(api, ben, payment(ben, aditi, 3333))
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["kind"] == "settlement"
    assert p["payers"] == [{"user_id": ben.id, "display_name": "Ben", "amount_minor": 3333}]
    assert [(s["user_id"], s["owed_minor"]) for s in p["shares"]] == [(aditi.id, 3333)]
    assert await owes(api, ben, aditi) == 0
    assert await owes(api, aditi, ben) == 0


async def test_receiver_can_record_too(api: Api, trio, dinner) -> None:
    aditi, ben, _ = trio
    r = await pay(api, aditi, payment(ben, aditi, 1000))
    assert r.status_code == 201
    assert await owes(api, ben, aditi) == 2333


async def test_paying_more_than_owed_flips_the_balance(api: Api, trio, dinner) -> None:
    """Chen owes Aditi S$33.33 and pays S$50: Aditi now owes Chen S$16.67."""
    aditi, _, chen = trio
    r = await pay(api, chen, payment(chen, aditi, 5000))
    assert r.status_code == 201, r.text
    assert await owes(api, aditi, chen) == 1667
    assert await owes(api, chen, aditi) == -1667


async def test_paying_someone_you_owe_nothing_means_they_owe_you(api: Api, trio, dinner) -> None:
    aditi, _, chen = trio
    assert (await pay(api, aditi, payment(aditi, chen, 1000))).status_code == 201
    assert await owes(api, chen, aditi) == 3333 + 1000
    # A currency with no debt at all works the same way.
    assert (await pay(api, chen, payment(chen, aditi, 500, currency="THB"))).status_code == 201
    assert await owes(api, aditi, chen, "THB") == 500


async def test_only_the_two_people_can_record(api: Api, trio, dinner) -> None:
    aditi, ben, chen = trio
    r = await pay(api, chen, payment(ben, aditi, 100))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/not-involved")
    r = await pay(api, ben, payment(ben, ben, 100))
    assert r.json()["type"].endswith("/same-person")
    ghost = str(uuid.uuid4())
    r = await pay(api, ben, {**payment(ben, aditi, 100), "receiver_id": ghost})
    assert r.json()["type"].endswith("/unknown-user")


async def test_bad_amounts_use_the_split_engine_errors(api: Api, trio, dinner) -> None:
    aditi, ben, _ = trio
    r = await pay(api, ben, payment(ben, aditi, 0))
    assert r.json()["type"].endswith("/invalid-total")
    r = await pay(api, ben, payment(ben, aditi, 100, currency="XXX"))
    assert r.json()["type"].endswith("/unsupported-currency")


async def test_unfriended_people_can_still_settle(api: Api, trio, dinner) -> None:
    aditi, ben, _ = trio
    await api.client.delete(f"/v1/friends/{aditi.id}", headers=ben.write())
    assert (await pay(api, ben, payment(ben, aditi, 3333))).status_code == 201


async def test_payments_show_in_the_feed(api: Api, trio, dinner) -> None:
    aditi, ben, _ = trio
    await pay(api, ben, payment(ben, aditi, 3333))
    feed = (await api.client.get("/v1/expenses", headers=aditi.auth)).json()["items"]
    assert [(e["kind"], e["name"]) for e in feed] == [
        ("settlement", "Payment"),
        ("expense", "Dinner"),
    ]


# --- Edit, delete, restore ----------------------------------------------------------------


async def test_edit_delete_and_restore_a_payment(api: Api, trio, dinner) -> None:
    aditi, ben, _ = trio
    p = (await pay(api, ben, payment(ben, aditi, 3333))).json()
    edit = {"amount_minor": 2000, "expense_date": "2026-11-18"}

    # Aditi corrects it to S$20: Ben owes S$13.33 again.
    r = await api.client.put(f"/v1/settlements/{p['id']}", json=edit, headers=aditi.write())
    assert r.status_code == 200, r.text
    assert r.json()["amount_minor"] == 2000
    assert r.json()["rev_no"] == 2
    assert await owes(api, ben, aditi) == 1333

    # Corrected again to S$40, more than the S$33.33 owed: Aditi owes Ben S$6.67.
    more = {**edit, "amount_minor": 4000}
    r = await api.client.put(f"/v1/settlements/{p['id']}", json=more, headers=ben.write())
    assert r.status_code == 200
    assert await owes(api, aditi, ben) == 667

    history = (await api.client.get(f"/v1/expenses/{p['id']}/revisions", headers=ben.auth)).json()
    assert [h["amount_minor"] for h in history["items"]] == [3333, 2000, 4000]

    # Ben says it was wrong: deleting it brings the debt back; restoring removes it again.
    assert (
        await api.client.delete(f"/v1/expenses/{p['id']}", headers=ben.write())
    ).status_code == 204
    assert await owes(api, ben, aditi) == 3333
    r = await api.client.post(f"/v1/expenses/{p['id']}/restore", headers=aditi.write())
    assert r.status_code == 200
    assert await owes(api, aditi, ben) == 667


async def test_wrong_edit_route_is_refused(api: Api, trio, dinner) -> None:
    aditi, ben, chen = trio
    p = (await pay(api, ben, payment(ben, aditi, 1000))).json()
    r = await api.client.put(
        f"/v1/expenses/{p['id']}", json=equal_split(aditi, [aditi, ben], 1000), headers=ben.write()
    )
    assert r.status_code == 409
    assert r.json()["type"].endswith("/is-a-settlement")
    edit = {"amount_minor": 500, "expense_date": "2026-11-18"}
    r = await api.client.put(f"/v1/settlements/{dinner['id']}", json=edit, headers=aditi.write())
    assert r.status_code == 409
    assert r.json()["type"].endswith("/not-a-settlement")
    # Chen isn't on Ben's payment, so for him it doesn't exist.
    r = await api.client.put(f"/v1/settlements/{p['id']}", json=edit, headers=chen.write())
    assert r.status_code == 404


# --- The user's scenario (2026-11-17) -----------------------------------------------------


async def test_payment_reduces_the_balance_not_a_specific_expense(api: Api) -> None:
    """Chen pays $20 split with Ben: Ben owes $10. Ben pays $10 and is square. Chen then
    edits the expense to $30: Ben's share is $15, he's paid $10, so he owes $5 more."""
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    await befriend(api, chen, ben)
    e = await add_expense(api, chen, equal_split(chen, [ben, chen], 2000))
    assert await owes(api, ben, chen) == 1000

    assert (await pay(api, ben, payment(ben, chen, 1000))).status_code == 201
    assert await owes(api, ben, chen) == 0

    r = await api.client.put(
        f"/v1/expenses/{e['id']}", json=equal_split(chen, [ben, chen], 3000), headers=chen.write()
    )
    assert r.status_code == 200
    assert await owes(api, ben, chen) == 500


async def test_two_payments_at_once_both_count(api: Api, trio, dinner) -> None:
    """Ben and Aditi both record Ben's S$33.33 at the same moment. Both are real records,
    so both count (Aditi then owes Ben S$33.33); either can delete the duplicate."""
    aditi, ben, _ = trio
    results = await asyncio.gather(
        pay(api, ben, payment(ben, aditi, 3333)),
        pay(api, aditi, payment(ben, aditi, 3333)),
    )
    assert [r.status_code for r in results] == [201, 201]
    assert await owes(api, aditi, ben) == 3333
    await api.client.delete(f"/v1/expenses/{results[1].json()['id']}", headers=ben.write())
    assert await owes(api, aditi, ben) == 0
