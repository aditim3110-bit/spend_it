"""Adding friends by QR code (PRD section 6A)."""

import uuid

from tests.support.api import Api

ADITI, BEN, CHEN = "+6591111111", "+6592222222", "+6593333333"


async def person(api: Api, phone: str, name: str | None) -> dict[str, str]:
    """Sign in and (optionally) set a name. Returns auth headers without a retry ticket."""
    session = await api.sign_in(phone)
    h = {"Authorization": f"Bearer {session['access_token']}"}
    if name:
        r = await api.client.patch("/v1/me", json={"display_name": name}, headers=ticket(h))
        assert r.status_code == 200
    return h


def ticket(h: dict[str, str]) -> dict[str, str]:
    return {**h, "Idempotency-Key": str(uuid.uuid4())}


async def code_of(api: Api, h: dict[str, str]) -> dict:
    r = await api.client.get("/v1/me/qr", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def scan(api: Api, h: dict[str, str], code: str):
    return await api.client.post("/v1/friends/connect", json={"code": code}, headers=ticket(h))


async def friend_names(api: Api, h: dict[str, str]) -> list[str]:
    r = await api.client.get("/v1/friends", headers=h)
    return [f["display_name"] for f in r.json()["items"]]


# --- My code ------------------------------------------------------------------------------


async def test_my_code_is_stable_and_is_a_spendit_link(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    first = await code_of(api, aditi)
    again = await code_of(api, aditi)
    assert first["code"] == again["code"]
    assert first["url"] == f"https://spendit.app/u/{first['code']}"
    assert len(first["code"]) >= 22  # 128 random bits


async def test_code_needs_a_name_first(api: Api) -> None:
    nameless = await person(api, ADITI, None)
    r = await api.client.get("/v1/me/qr", headers=nameless)
    assert r.status_code == 422
    assert r.json()["type"].endswith("/name-required")


# --- Scanning -----------------------------------------------------------------------------


async def test_scanning_makes_both_people_friends_instantly(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    r = await scan(api, ben, (await code_of(api, aditi))["code"])
    assert r.status_code == 200
    assert r.json()["friend"]["display_name"] == "Aditi"
    assert r.json()["already_friends"] is False
    # Mutual: each sees the other, with no approval step.
    assert await friend_names(api, ben) == ["Aditi"]
    assert await friend_names(api, aditi) == ["Ben"]
    items = (await api.client.get("/v1/friends", headers=aditi)).json()["items"]
    assert items[0]["source"] == "qr"


async def test_scanning_the_full_link_also_works(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    url = (await code_of(api, aditi))["url"]
    assert (await scan(api, ben, url)).status_code == 200


async def test_scanning_again_is_harmless(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    code = (await code_of(api, aditi))["code"]
    await scan(api, ben, code)
    r = await scan(api, ben, code)
    assert r.status_code == 200
    assert r.json()["already_friends"] is True
    assert await friend_names(api, ben) == ["Aditi"]  # no duplicate
    # Aditi scanning Ben back is also fine.
    r = await scan(api, aditi, (await code_of(api, ben))["code"])
    assert r.json()["already_friends"] is True


async def test_cannot_add_yourself(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    r = await scan(api, aditi, (await code_of(api, aditi))["code"])
    assert r.status_code == 422
    assert r.json()["type"].endswith("/cannot-add-yourself")


async def test_unknown_code_is_not_found(api: Api) -> None:
    ben = await person(api, BEN, "Ben")
    r = await scan(api, ben, "A" * 22)
    assert r.status_code == 404
    assert r.json()["type"].endswith("/code-not-found")


async def test_scanner_needs_a_name_first(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    nameless = await person(api, BEN, None)
    r = await scan(api, nameless, (await code_of(api, aditi))["code"])
    assert r.status_code == 422


async def test_connecting_needs_a_retry_ticket(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    code = (await code_of(api, aditi))["code"]
    r = await api.client.post("/v1/friends/connect", json={"code": code}, headers=ben)
    assert r.status_code == 400


async def test_thirty_scans_per_hour(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    code = (await code_of(api, aditi))["code"]
    for _ in range(30):
        assert (await scan(api, ben, code)).status_code == 200
    r = await scan(api, ben, code)
    assert r.status_code == 429
    assert "retry-after" in r.headers


# --- Reset my code -----------------------------------------------------------------------


async def test_reset_kills_the_old_code_but_keeps_friends(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    chen = await person(api, CHEN, "Chen")
    old = (await code_of(api, aditi))["code"]
    await scan(api, ben, old)

    r = await api.client.post("/v1/me/qr/reset", headers=ticket(aditi))
    assert r.status_code == 200
    new = r.json()["code"]
    assert new != old
    assert (await code_of(api, aditi))["code"] == new

    assert (await scan(api, chen, old)).status_code == 404  # leaked screenshot is useless
    assert (await scan(api, chen, new)).status_code == 200
    assert sorted(await friend_names(api, aditi)) == ["Ben", "Chen"]  # Ben was kept


# --- Removing ----------------------------------------------------------------------------


async def test_removing_a_friend_removes_it_for_both(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    code = (await code_of(api, aditi))["code"]
    friend = (await scan(api, ben, code)).json()["friend"]

    r = await api.client.delete(f"/v1/friends/{friend['id']}", headers=ticket(ben))
    assert r.status_code == 204
    assert await friend_names(api, ben) == []
    assert await friend_names(api, aditi) == []
    # Removing again is harmless, and they can reconnect later.
    r = await api.client.delete(f"/v1/friends/{friend['id']}", headers=ticket(ben))
    assert r.status_code == 204
    assert (await scan(api, ben, code)).json()["already_friends"] is False


# --- Listing -----------------------------------------------------------------------------


async def test_friend_list_pages_newest_first(api: Api) -> None:
    me = await person(api, ADITI, "Aditi")
    for phone, name in [("+6594444441", "P1"), ("+6594444442", "P2"), ("+6594444443", "P3")]:
        other = await person(api, phone, name)
        await scan(api, me, (await code_of(api, other))["code"])

    first = (await api.client.get("/v1/friends?limit=2", headers=me)).json()
    assert [f["display_name"] for f in first["items"]] == ["P3", "P2"]
    assert first["next_cursor"]
    second = (
        await api.client.get(f"/v1/friends?limit=2&cursor={first['next_cursor']}", headers=me)
    ).json()
    assert [f["display_name"] for f in second["items"]] == ["P1"]
    assert second["next_cursor"] is None


async def test_bad_cursor_is_rejected(api: Api) -> None:
    me = await person(api, ADITI, "Aditi")
    r = await api.client.get("/v1/friends?cursor=not-a-cursor", headers=me)
    assert r.status_code == 422
    assert r.json()["type"].endswith("/invalid-cursor")


async def test_friends_need_sign_in(api: Api) -> None:
    assert (await api.client.get("/v1/friends")).status_code == 401
    assert (await api.client.get("/v1/me/qr")).status_code == 401


# --- The web page for people without the app --------------------------------------------


async def test_web_page_shows_first_name_only(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi Maheshwari")
    code = (await code_of(api, aditi))["code"]
    r = await api.client.get(f"/u/{code}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Add Aditi on SpendIt" in r.text
    assert "Maheshwari" not in r.text  # first name only
    assert ADITI not in r.text and "91111111" not in r.text  # never the phone number
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert r.headers["cache-control"] == "no-store"


async def test_web_page_for_unknown_or_reset_code(api: Api) -> None:
    aditi = await person(api, ADITI, "Aditi")
    old = (await code_of(api, aditi))["code"]
    await api.client.post("/v1/me/qr/reset", headers=ticket(aditi))
    r = await api.client.get(f"/u/{old}")
    assert r.status_code == 404
    assert "isn't valid anymore" in r.text
    assert "Aditi" not in r.text


async def test_web_page_escapes_names(api: Api) -> None:
    """A name containing HTML must be shown as text, never run as code."""
    aditi = await person(api, ADITI, "<script>alert(1)</script>")
    code = (await code_of(api, aditi))["code"]
    r = await api.client.get(f"/u/{code}")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
