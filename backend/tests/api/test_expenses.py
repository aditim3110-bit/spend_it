"""Adding and viewing direct expenses (PRD section 7; decisions of 2026-11-17)."""

import uuid

import pytest

from tests.support.api import Api
from tests.support.people import Person, befriend, equal_split, owed, person

ADITI, BEN, CHEN, DEV = "+6591111111", "+6592222222", "+6593333333", "+6594444444"


@pytest.fixture
async def trio(api: Api) -> tuple[Person, Person, Person]:
    """Aditi is friends with Ben and with Chen. Ben and Chen don't know each other."""
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    await befriend(api, aditi, ben)
    await befriend(api, aditi, chen)
    return aditi, ben, chen


async def create(api: Api, who: Person, body: dict):
    return await api.client.post("/v1/expenses", json=body, headers=who.write())


# --- Creating -----------------------------------------------------------------------------


async def test_equal_split_payer_takes_the_extra_cent(api: Api, trio) -> None:
    aditi, ben, chen = trio
    r = await create(api, aditi, equal_split(aditi, [aditi, ben, chen], 10000))
    assert r.status_code == 201, r.text
    e = r.json()
    # S$100.00 / 3: the single payer absorbs the rounding (PRD section 7).
    assert owed(e) == {"Aditi": 3334, "Ben": 3333, "Chen": 3333}
    assert e["payers"] == [{"user_id": aditi.id, "display_name": "Aditi", "amount_minor": 10000}]
    assert e["rev_no"] == 1
    assert e["context_type"] == "direct"
    assert e["kind"] == "expense"
    assert e["split_mode"] == "equal"
    assert e["created_by"] == e["updated_by"] == aditi.id
    assert e["deleted_at"] is None


async def test_get_returns_the_saved_expense_to_everyone_on_it(api: Api, trio) -> None:
    aditi, ben, chen = trio
    created = (await create(api, aditi, equal_split(aditi, [aditi, ben, chen], 10000))).json()
    for who in (aditi, ben, chen):
        r = await api.client.get(f"/v1/expenses/{created['id']}", headers=who.auth)
        assert r.status_code == 200
        assert r.json() == created


async def test_outsiders_get_404_not_403(api: Api, trio) -> None:
    aditi, ben, _ = trio
    dev = await person(api, DEV, "Dev")
    created = (await create(api, aditi, equal_split(aditi, [aditi, ben], 1000))).json()
    r = await api.client.get(f"/v1/expenses/{created['id']}", headers=dev.auth)
    assert r.status_code == 404
    missing = await api.client.get(f"/v1/expenses/{uuid.uuid4()}", headers=dev.auth)
    assert missing.status_code == 404
    assert r.json() == missing.json()  # indistinguishable from "doesn't exist"


async def test_exact_percent_and_shares_keep_what_was_typed(api: Api, trio) -> None:
    aditi, ben, chen = trio
    base = equal_split(aditi, [], 10000)

    exact = {
        **base,
        "split": {
            "mode": "exact",
            "shares": [{"user_id": aditi.id, "value": 2000}, {"user_id": ben.id, "value": 8000}],
        },
    }
    e = (await create(api, aditi, exact)).json()
    assert owed(e) == {"Aditi": 2000, "Ben": 8000}

    percent = {
        **base,
        "split": {
            "mode": "percent",
            "shares": [
                {"user_id": aditi.id, "value": 3333},
                {"user_id": ben.id, "value": 3333},
                {"user_id": chen.id, "value": 3334},
            ],
        },
    }
    e = (await create(api, aditi, percent)).json()
    assert owed(e) == {"Aditi": 3333, "Ben": 3333, "Chen": 3334}
    assert {s["display_name"]: s["input_value"] for s in e["shares"]} == {
        "Aditi": 3333,
        "Ben": 3333,
        "Chen": 3334,
    }

    shares = {
        **base,
        "split": {
            "mode": "shares",
            "shares": [
                {"user_id": aditi.id, "value": 2},
                {"user_id": ben.id, "value": 1},
                {"user_id": chen.id, "value": 1},
            ],
        },
    }
    e = (await create(api, aditi, shares)).json()
    assert owed(e) == {"Aditi": 5000, "Ben": 2500, "Chen": 2500}


async def test_several_payers_and_zero_decimal_currency(api: Api, trio) -> None:
    aditi, ben, chen = trio
    body = equal_split(aditi, [aditi, ben, chen], 1000, currency="JPY")
    body["payers"] = [
        {"user_id": aditi.id, "amount_minor": 600},
        {"user_id": ben.id, "amount_minor": 400},
    ]
    e = (await create(api, aditi, body)).json()
    # ¥1000 / 3 with several payers: ties go by ID, so exactly one person gets 334.
    assert sorted(owed(e).values()) == [333, 333, 334]
    assert e["currency"] == "JPY"


async def test_owed_the_full_amount_shortcut(api: Api, trio) -> None:
    """ "You are owed the full amount": Aditi paid, Ben owes all of it (stored as exact)."""
    aditi, ben, _ = trio
    body = equal_split(aditi, [], 4250)
    body["split"] = {
        "mode": "exact",
        "shares": [{"user_id": aditi.id, "value": 0}, {"user_id": ben.id, "value": 4250}],
    }
    e = (await create(api, aditi, body)).json()
    assert owed(e) == {"Aditi": 0, "Ben": 4250}


# --- Who can be on an expense -------------------------------------------------------------


async def test_only_friends_can_be_added(api: Api, trio) -> None:
    aditi, ben, _ = trio
    dev = await person(api, DEV, "Dev")
    r = await create(api, aditi, equal_split(aditi, [aditi, ben, dev], 900))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/not-friends")
    assert r.json()["errors"] == [{"user_id": dev.id}]


async def test_you_must_be_on_the_expense(api: Api, trio) -> None:
    aditi, ben, chen = trio
    r = await create(api, aditi, equal_split(ben, [ben, chen], 900))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/not-involved")


async def test_unknown_people_are_rejected(api: Api, trio) -> None:
    aditi, _, _ = trio
    ghost = Person(id=str(uuid.uuid4()), name="Ghost", phone="", auth={})
    r = await create(api, aditi, equal_split(aditi, [aditi, ghost], 900))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/unknown-user")
    assert r.json()["errors"] == [{"user_id": ghost.id}]


async def test_everyone_needs_a_name(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    nameless = await person(api, BEN, None)
    await befriend(api, aditi, nameless)
    r = await create(api, aditi, equal_split(aditi, [aditi, nameless], 900))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/name-required")
    assert r.json()["errors"] == [{"user_id": nameless.id}]

    # And you need one yourself.
    r = await create(api, nameless, equal_split(nameless, [nameless, aditi], 900))
    assert r.status_code == 422
    assert r.json()["type"].endswith("/name-required")


async def test_people_on_a_shared_expense_become_friends(api: Api, trio) -> None:
    aditi, ben, chen = trio
    assert (
        await create(api, aditi, equal_split(aditi, [aditi, ben, chen], 900))
    ).status_code == 201
    r = await api.client.get("/v1/friends", headers=ben.auth)
    sources = {f["display_name"]: f["source"] for f in r.json()["items"]}
    assert sources == {"Aditi": "phone_email", "Chen": "expense"}


# --- The server decides -------------------------------------------------------------------


async def test_split_errors_use_the_same_problems_as_preview(api: Api, trio) -> None:
    aditi, ben, _ = trio
    body = equal_split(aditi, [aditi, ben], 1000)
    body["payers"][0]["amount_minor"] = 999
    r = await create(api, aditi, body)
    assert r.status_code == 422
    assert r.json()["type"].endswith("/sum-mismatch")
    assert r.json()["errors"] == [{"code": "SumMismatch", "side": "payers", "remainder": 1}]

    r = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000, currency="XXX"))
    assert r.json()["type"].endswith("/unsupported-currency")


async def test_client_cannot_send_its_own_amounts_owed(api: Api, trio) -> None:
    aditi, ben, _ = trio
    body = equal_split(aditi, [aditi, ben], 1000)
    body["split"]["shares"][1]["owed_minor"] = 0  # trying to get out of paying
    r = await create(api, aditi, body)
    assert r.status_code == 422
    assert r.json()["type"].endswith("/validation-error")


async def test_name_and_notes_limits(api: Api, trio) -> None:
    aditi, ben, _ = trio
    for bad in ({"name": "   "}, {"name": "x" * 121}, {"notes": "x" * 2001}):
        r = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000, **bad))
        assert r.status_code == 422, bad
    ok = await create(api, aditi, equal_split(aditi, [aditi, ben], 1000, name="  Taxi  "))
    assert ok.json()["name"] == "Taxi"


async def test_retry_with_same_ticket_does_not_create_twice(api: Api, trio) -> None:
    aditi, ben, _ = trio
    headers = aditi.write()
    body = equal_split(aditi, [aditi, ben], 1000)
    first = await api.client.post("/v1/expenses", json=body, headers=headers)
    again = await api.client.post("/v1/expenses", json=body, headers=headers)
    assert again.status_code == 201
    assert again.headers["idempotent-replayed"] == "true"
    assert again.json()["id"] == first.json()["id"]
    feed = await api.client.get("/v1/expenses", headers=aditi.auth)
    assert len(feed.json()["items"]) == 1
