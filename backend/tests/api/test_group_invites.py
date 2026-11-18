"""Invite links and join requests (PRD section 9)."""

import pytest

from tests.support.api import Api
from tests.support.groups import make_group, member_names
from tests.support.people import Person, befriend, person

ADITI, BEN, CHEN, DEV = "+6591111111", "+6592222222", "+6593333333", "+6594444444"


@pytest.fixture
async def setup(api: Api) -> tuple[Person, Person, Person, dict]:
    """Aditi and Ben are in Bali 2027. Dev, a stranger, will use a link."""
    aditi = await person(api, ADITI, "Aditi")
    ben = await person(api, BEN, "Ben")
    dev = await person(api, DEV, "Dev")
    await befriend(api, aditi, ben)
    g = await make_group(api, aditi, [ben])
    return aditi, ben, dev, g


async def invite(api: Api, who: Person, g: dict, approval: bool = False) -> dict:
    r = await api.client.post(
        f"/v1/groups/{g['id']}/invites", json={"requires_approval": approval}, headers=who.write()
    )
    assert r.status_code == 201, r.text
    return r.json()


async def accept(api: Api, who: Person, token: str):
    return await api.client.post(f"/v1/invites/{token}/accept", headers=who.write())


async def names(api: Api, who: Person, g: dict) -> list:
    return member_names((await api.client.get(f"/v1/groups/{g['id']}", headers=who.auth)).json())


async def test_open_link_joins_straight_away(api: Api, setup) -> None:
    aditi, ben, dev, g = setup
    inv = await invite(api, ben, g)  # any member can make a link
    assert inv["url"] == f"https://spendit.app/join/{inv['token']}"
    assert len(inv["token"]) >= 22  # 128 random bits

    preview = await api.client.get(f"/v1/invites/{inv['token']}", headers=dev.auth)
    assert preview.json() == {
        "group_id": g["id"],
        "name": "Bali 2027",
        "type": "trip",
        "member_count": 2,
        "requires_approval": False,
        "already_member": False,
    }
    r = await accept(api, dev, inv["token"])
    assert r.status_code == 200
    assert r.json() == {"status": "joined", "group_id": g["id"], "request_id": None}
    assert await names(api, aditi, g) == ["Aditi", "Ben", "Dev"]
    # Dev is now friends with everyone in the group.
    friends = (await api.client.get("/v1/friends", headers=dev.auth)).json()["items"]
    assert {f["display_name"]: f["source"] for f in friends} == {"Aditi": "group", "Ben": "group"}

    again = await accept(api, dev, inv["token"])
    assert again.json()["status"] == "already_member"


async def test_approval_flow(api: Api, setup) -> None:
    aditi, ben, dev, g = setup
    inv = await invite(api, aditi, g, approval=True)
    r = await accept(api, dev, inv["token"])
    assert r.status_code == 202
    assert r.json()["status"] == "pending"
    rid = r.json()["request_id"]
    # Asking again doesn't create a second request.
    assert (await accept(api, dev, inv["token"])).json()["request_id"] == rid
    assert await names(api, aditi, g) == ["Aditi", "Ben"]

    url = f"/v1/groups/{g['id']}/join-requests"
    pending = (await api.client.get(url, headers=ben.auth)).json()["items"]  # any member
    assert [(p["id"], p["display_name"]) for p in pending] == [(rid, "Dev")]
    assert (await api.client.get(url, headers=dev.auth)).status_code == 404  # not in yet

    # Ben approves a link Aditi made: any member can answer.
    assert (await api.client.post(f"{url}/{rid}/approve", headers=ben.write())).status_code == 204
    assert await names(api, aditi, g) == ["Aditi", "Ben", "Dev"]
    assert (await api.client.get(url, headers=aditi.auth)).json()["items"] == []
    r = await api.client.post(f"{url}/{rid}/decline", headers=aditi.write())
    assert r.status_code == 409  # already answered


async def test_declined_request(api: Api, setup) -> None:
    aditi, _, dev, g = setup
    inv = await invite(api, aditi, g, approval=True)
    rid = (await accept(api, dev, inv["token"])).json()["request_id"]
    url = f"/v1/groups/{g['id']}/join-requests/{rid}/decline"
    assert (await api.client.post(url, headers=aditi.write())).status_code == 204
    assert await names(api, aditi, g) == ["Aditi", "Ben"]
    # They can ask again later through a link.
    assert (await accept(api, dev, inv["token"])).json()["status"] == "pending"


async def test_revoked_and_expired_links(api: Api, setup, db_execute) -> None:
    aditi, ben, dev, g = setup
    mine = await invite(api, ben, g)
    theirs = await invite(api, aditi, g)
    base = f"/v1/groups/{g['id']}/invites"
    # Any member can turn off any of the group's links, including someone else's.
    assert (
        await api.client.delete(f"{base}/{mine['token']}", headers=aditi.write())
    ).status_code == 204
    r = await accept(api, dev, mine["token"])
    assert r.status_code == 410
    assert r.json()["type"].endswith("/invite-revoked")

    await db_execute(
        "UPDATE group_invites SET expires_at = now() - interval '1 second' WHERE token = :t",
        t=theirs["token"],
    )
    r = await api.client.get(f"/v1/invites/{theirs['token']}", headers=dev.auth)
    assert r.status_code == 410
    assert r.json()["type"].endswith("/invite-expired")

    assert (await api.client.get("/v1/invites/nonsense-token", headers=dev.auth)).status_code == 404


async def test_archived_group_link_cannot_be_used(api: Api, setup) -> None:
    aditi, _, dev, g = setup
    inv = await invite(api, aditi, g)
    await api.client.post(f"/v1/groups/{g['id']}/archive", headers=aditi.write())
    r = await accept(api, dev, inv["token"])
    assert r.status_code == 409
    assert r.json()["type"].endswith("/group-archived")


async def test_need_a_name_to_join(api: Api, setup) -> None:
    aditi, _, _, g = setup
    nameless = await person(api, CHEN, None)
    inv = await invite(api, aditi, g)
    r = await accept(api, nameless, inv["token"])
    assert r.json()["type"].endswith("/name-required")
