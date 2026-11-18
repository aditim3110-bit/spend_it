"""Group balances and Smart Settle (PRD sections 8 and 9; decisions of 2026-11-17)."""

import pytest

from tests.support.api import Api
from tests.support.groups import make_group
from tests.support.people import Person, befriend, equal_split, person

ADITI, BEN, CHEN = "+6591111111", "+6592222222", "+6593333333"


@pytest.fixture
async def bali(api: Api) -> tuple[Person, Person, Person, dict]:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    await befriend(api, aditi, ben)
    await befriend(api, aditi, chen)
    g = await make_group(api, aditi, [ben, chen])
    return aditi, ben, chen, g


async def owes_in_group(api: Api, payer: Person, receiver: Person, g: dict, amount: int):
    """`payer` pays a group expense that only `receiver` shares, so receiver owes payer."""
    body = {**equal_split(payer, [receiver], amount), "group_id": g["id"]}
    r = await api.client.post("/v1/expenses", json=body, headers=payer.write())
    assert r.status_code == 201, r.text


async def balances(api: Api, who: Person, g: dict, **params) -> dict:
    r = await api.client.get(f"/v1/groups/{g['id']}/balances", headers=who.auth, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def transfers(b: dict, names: dict[str, str]) -> list[tuple[str, str, int]]:
    return sorted(
        (names[t["from_user_id"]], names[t["to_user_id"]], t["amount_minor"])
        for t in b["transfers"]
    )


@pytest.fixture
def names(bali) -> dict[str, str]:
    aditi, ben, chen, _ = bali
    return {aditi.id: "Aditi", ben.id: "Ben", chen.id: "Chen"}


async def test_chain_becomes_one_payment(api: Api, bali, names) -> None:
    """Aditi owes Ben 10 and Ben owes Chen 10: with Smart Settle, Aditi pays Chen 10."""
    aditi, ben, chen, g = bali
    await owes_in_group(api, ben, aditi, g, 1000)  # Ben paid for Aditi
    await owes_in_group(api, chen, ben, g, 1000)  # Chen paid for Ben
    b = await balances(api, ben, g)
    assert b["smart_settle"] is True
    assert b["view"] == "simplified"
    assert transfers(b, names) == [("Aditi", "Chen", 1000)]
    nets = {names[m["user_id"]]: m["amounts"] for m in b["members"]}
    assert nets == {
        "Aditi": [{"currency": "SGD", "amount_minor": -1000}],
        "Ben": [],  # square overall
        "Chen": [{"currency": "SGD", "amount_minor": 1000}],
    }
    detailed = await balances(api, ben, g, view="detailed")
    assert transfers(detailed, names) == [("Aditi", "Ben", 1000), ("Ben", "Chen", 1000)]


async def test_smart_settle_off_shows_plain_debts(api: Api, bali, names) -> None:
    aditi, ben, chen, g = bali
    await owes_in_group(api, ben, aditi, g, 1000)
    await owes_in_group(api, chen, ben, g, 1000)
    await api.client.patch(
        f"/v1/groups/{g['id']}", json={"smart_settle": False}, headers=chen.write()
    )
    b = await balances(api, aditi, g)
    assert (b["smart_settle"], b["view"]) == (False, "detailed")
    assert transfers(b, names) == [("Aditi", "Ben", 1000), ("Ben", "Chen", 1000)]


async def test_never_told_to_pay_someone_who_is_not_a_friend(api: Api, bali, names) -> None:
    aditi, ben, chen, g = bali
    await owes_in_group(api, ben, aditi, g, 1000)
    await owes_in_group(api, chen, ben, g, 1000)
    await api.client.delete(f"/v1/friends/{chen.id}", headers=aditi.write())
    b = await balances(api, aditi, g)
    assert transfers(b, names) == [("Aditi", "Ben", 1000), ("Ben", "Chen", 1000)]


async def test_group_payment_settles_it_and_lets_people_leave(api: Api, bali, names) -> None:
    aditi, ben, chen, g = bali
    await owes_in_group(api, ben, aditi, g, 1000)
    await owes_in_group(api, chen, ben, g, 1000)
    r = await api.client.delete(f"/v1/groups/{g['id']}/members/{aditi.id}", headers=aditi.write())
    assert r.json()["type"].endswith("/balance-not-zero")

    # Aditi pays Chen as Smart Settle says, recorded inside the group.
    r = await api.client.post(
        "/v1/settlements",
        json={"payer_id": aditi.id, "receiver_id": chen.id, "amount_minor": 1000,
              "currency": "SGD", "expense_date": "2026-11-18", "group_id": g["id"]},
        headers=aditi.write(),
    )  # fmt: skip
    assert r.status_code == 201, r.text
    b = await balances(api, ben, g)
    assert b["transfers"] == []
    assert all(m["amounts"] == [] for m in b["members"])
    for p in (aditi, ben, chen):
        r = await api.client.delete(f"/v1/groups/{g['id']}/members/{p.id}", headers=p.write())
        assert r.status_code == 204, (p.name, r.text)


async def test_group_payment_needs_both_people_in_the_group(api: Api, bali) -> None:
    aditi, _, _, g = bali
    dev = await person(api, "+6594444444", "Dev")
    await befriend(api, aditi, dev)
    r = await api.client.post(
        "/v1/settlements",
        json={"payer_id": aditi.id, "receiver_id": dev.id, "amount_minor": 100,
              "currency": "SGD", "expense_date": "2026-11-18", "group_id": g["id"]},
        headers=aditi.write(),
    )  # fmt: skip
    assert r.json()["type"].endswith("/not-members")


async def test_outsiders_cannot_see_group_balances(api: Api, bali) -> None:
    _, _, _, g = bali
    dev = await person(api, "+6594444444", "Dev")
    r = await api.client.get(f"/v1/groups/{g['id']}/balances", headers=dev.auth)
    assert r.status_code == 404


# --- The home screen nets everything per person (the user's examples, 2026-11-17) -------


async def home_line(api: Api, who: Person, other: Person) -> int:
    r = await api.client.get(f"/v1/balances/friends/{other.id}", headers=who.auth)
    return sum(a["amount_minor"] for a in r.json()["amounts"])  # positive: they owe me


async def test_group_payment_and_direct_debt_cancel_out(api: Api, bali) -> None:
    """In the group Smart Settle says Aditi pays Chen 10; outside, Chen owes Aditi 10:
    square. If Chen owed Aditi only 8 outside, Aditi pays Chen 2."""
    aditi, ben, chen, g = bali
    await owes_in_group(api, ben, aditi, g, 1000)
    await owes_in_group(api, chen, ben, g, 1000)
    assert await home_line(api, aditi, chen) == -1000  # Aditi owes Chen, via the group

    direct = equal_split(aditi, [chen], 800)  # Aditi paid 8 for Chen, outside the group
    assert (
        await api.client.post("/v1/expenses", json=direct, headers=aditi.write())
    ).status_code == 201
    assert await home_line(api, aditi, chen) == -200  # Aditi pays Chen 2
    detail = (await api.client.get(f"/v1/balances/friends/{chen.id}", headers=aditi.auth)).json()
    contexts = {(c["context_type"], c["group_id"]): c["amounts"] for c in detail["contexts"]}
    assert contexts == {
        ("direct", None): [{"currency": "SGD", "amount_minor": 800}],
        ("group", g["id"]): [{"currency": "SGD", "amount_minor": -1000}],
    }

    top_up = equal_split(aditi, [chen], 200)
    assert (
        await api.client.post("/v1/expenses", json=top_up, headers=aditi.write())
    ).status_code == 201
    assert await home_line(api, aditi, chen) == 0  # square
    # The home screen's list leaves out people you're square with, and Ben is square too.
    home = (await api.client.get("/v1/balances", headers=aditi.auth)).json()
    assert home["people"] == []


# --- Leaving when you're square overall but in the middle of debts (found by Hypothesis) --


async def test_middle_person_leaves_only_if_not_on_the_settle_up_list(api: Api, bali) -> None:
    """Ben owes Aditi 5 and Chen owes Ben 5, so Ben is square overall. With Smart Settle
    (Chen pays Aditi) Ben can leave; with it off, Ben is still on two plain debts."""
    aditi, ben, chen, g = bali
    await owes_in_group(api, aditi, ben, g, 500)  # Aditi paid for Ben: Ben owes Aditi
    await owes_in_group(api, ben, chen, g, 500)  # Ben paid for Chen: Chen owes Ben
    url = f"/v1/groups/{g['id']}"

    await api.client.patch(url, json={"smart_settle": False}, headers=aditi.write())
    r = await api.client.delete(f"{url}/members/{ben.id}", headers=ben.write())
    assert r.status_code == 409
    assert r.json()["type"].endswith("/balance-not-zero")

    await api.client.patch(url, json={"smart_settle": True}, headers=aditi.write())
    assert (
        await api.client.delete(f"{url}/members/{ben.id}", headers=ben.write())
    ).status_code == 204

    # Turning Smart Settle off now would put Ben (who left) back on the list: refused.
    r = await api.client.patch(url, json={"smart_settle": False}, headers=aditi.write())
    assert r.status_code == 409
    assert r.json()["type"].endswith("/former-member-debts")
    b = await balances(api, aditi, g)
    assert b["smart_settle"] is True
    names = {aditi.id: "Aditi", chen.id: "Chen"}
    assert transfers(b, names) == [("Chen", "Aditi", 500)]
