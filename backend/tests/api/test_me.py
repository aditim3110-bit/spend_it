"""Editing your profile: the 'What should friends call you?' screen (PRD section 6)."""

import uuid

from tests.support.api import Api


async def patch(api: Api, headers: dict, body: dict):
    h = {**headers, "Idempotency-Key": str(uuid.uuid4())}
    return await api.client.patch("/v1/me", json=body, headers=h)


async def test_setting_a_name_completes_onboarding(api: Api) -> None:
    h = await api.headers()
    r = await patch(api, h, {"display_name": "  Aditi  "})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Aditi"  # trimmed
    assert r.json()["needs_name"] is False
    me = await api.client.get("/v1/me", headers=h)
    assert me.json()["display_name"] == "Aditi"


async def test_only_sent_fields_change(api: Api) -> None:
    h = await api.headers()
    await patch(api, h, {"display_name": "Aditi"})
    r = await patch(api, h, {"default_currency": "SGD", "home_country": "SG"})
    body = r.json()
    assert (body["display_name"], body["default_currency"], body["home_country"]) == (
        "Aditi",
        "SGD",
        "SG",
    )


async def test_repeated_spaces_inside_a_name_are_collapsed(api: Api) -> None:
    h = await api.headers()
    r = await patch(api, h, {"display_name": "Chen    Wei"})
    assert r.json()["display_name"] == "Chen Wei"


async def test_invalid_profile_changes_are_rejected(api: Api) -> None:
    h = await api.headers()
    for body in (
        {"display_name": "   "},  # blank
        {"display_name": None},  # can't remove a name
        {"display_name": "x" * 81},  # too long
        {"default_currency": "XYZ"},  # not a real currency
        {"default_currency": "XAU"},  # gold isn't money between friends
        {"default_currency": "sgd"},  # must be the ISO code
        {"home_country": "Singapore"},
        {"nickname": "Adi"},  # unknown field
        {},  # nothing to change
    ):
        r = await patch(api, h, body)
        assert r.status_code == 422, body
        assert r.headers["content-type"] == "application/problem+json"


async def test_profile_edit_needs_a_retry_ticket(api: Api) -> None:
    h = await api.headers(key=False)
    r = await api.client.patch("/v1/me", json={"display_name": "Aditi"}, headers=h)
    assert r.status_code == 400
