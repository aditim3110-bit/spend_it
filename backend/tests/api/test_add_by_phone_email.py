"""Adding a friend by typing their phone number or email (PRD section 6A)."""

from tests.api.test_friends import ADITI, BEN, friend_names, person, ticket
from tests.support.api import Api


async def lookup(api: Api, h: dict, value: str, kind: str = "phone"):
    return await api.client.post(
        "/v1/friends/lookup", json={"kind": kind, "value": value}, headers=h
    )


async def add(api: Api, h: dict, value: str, kind: str = "phone"):
    return await api.client.post(
        "/v1/friends/add", json={"kind": kind, "value": value}, headers=ticket(h)
    )


async def test_lookup_shows_first_name_only(api: Api) -> None:
    await person(api, ADITI, "Aditi Maheshwari")
    ben = await person(api, BEN, "Ben")
    r = await lookup(api, ben, "9111 1111")  # typed locally, found as +65 9111 1111
    assert r.status_code == 200
    assert r.json() == {
        "on_spendit": True,
        "person": {"first_name": "Aditi", "avatar_url": None},
    }
    assert "Maheshwari" not in r.text and ADITI not in r.text


async def test_lookup_of_someone_not_on_spendit(api: Api) -> None:
    ben = await person(api, BEN, "Ben")
    r = await lookup(api, ben, "+6598765432")
    assert r.json() == {"on_spendit": False, "person": None}


async def test_lookup_needs_no_retry_ticket_and_changes_nothing(api: Api) -> None:
    await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    assert (await lookup(api, ben, ADITI)).status_code == 200  # no Idempotency-Key sent
    assert await friend_names(api, ben) == []


async def test_adding_by_phone_is_instant_and_mutual(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    r = await add(api, ben, ADITI)
    assert r.status_code == 200
    assert r.json()["friend"]["display_name"] == "Aditi"
    assert r.json()["already_friends"] is False
    assert await friend_names(api, ben) == ["Aditi"]
    assert await friend_names(api, aditi) == ["Ben"]  # no approval needed
    items = (await api.client.get("/v1/friends", headers=aditi)).json()["items"]
    assert items[0]["source"] == "phone_email"


async def test_adding_by_email_ignores_capital_letters(api: Api) -> None:
    session = await api.sign_in("Aditi@Example.com", kind="email")
    aditi = {"Authorization": f"Bearer {session['access_token']}"}
    await api.client.patch("/v1/me", json={"display_name": "Aditi"}, headers=ticket(aditi))
    ben = await person(api, BEN, "Ben")
    r = await add(api, ben, "ADITI@example.com", kind="email")
    assert r.status_code == 200


async def test_not_on_spendit_suggests_an_invite(api: Api) -> None:
    ben = await person(api, BEN, "Ben")
    r = await add(api, ben, "+6598765432")
    assert r.status_code == 404
    body = r.json()
    assert body["type"].endswith("/not-on-spendit")
    assert body["errors"] == [{"invite_url": "https://spendit.app"}]  # shared from Ben's phone


async def test_adding_twice_and_adding_yourself(api: Api) -> None:
    await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    await add(api, ben, ADITI)
    again = await add(api, ben, ADITI)
    assert again.json()["already_friends"] is True
    me = await add(api, ben, BEN)
    assert me.status_code == 422
    assert me.json()["type"].endswith("/cannot-add-yourself")


async def test_invalid_number_is_rejected(api: Api) -> None:
    ben = await person(api, BEN, "Ben")
    r = await add(api, ben, "12")
    assert r.status_code == 422


async def test_checks_and_adds_share_a_limit_of_30_per_hour(api: Api) -> None:
    ben = await person(api, BEN, "Ben")
    for i in range(20):
        assert (await lookup(api, ben, f"+65981234{i:02d}")).status_code == 200
    for i in range(10):
        assert (await add(api, ben, f"+65981235{i:02d}")).status_code == 404
    assert (await lookup(api, ben, "+6598123600")).status_code == 429
    assert (await add(api, ben, "+6598123601")).status_code == 429


async def test_adding_needs_a_retry_ticket_and_a_name(api: Api) -> None:
    await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, None)
    r = await api.client.post(
        "/v1/friends/add", json={"kind": "phone", "value": ADITI}, headers=ben
    )
    assert r.status_code == 400  # no ticket
    r = await add(api, ben, ADITI)
    assert r.status_code == 422  # no name yet
    assert r.json()["type"].endswith("/name-required")
