"""Helpers for group tests."""

from typing import Any

from tests.support.api import Api
from tests.support.people import Person


async def make_group(
    api: Api, owner: Person, members: list[Person] | None = None, **extra: Any
) -> dict[str, Any]:
    body = {
        "name": "Bali 2027",
        "type": "trip",
        "default_currency": "SGD",
        "member_ids": [m.id for m in members or []],
        **extra,
    }
    r = await api.client.post("/v1/groups", json=body, headers=owner.write())
    assert r.status_code == 201, r.text
    return r.json()


def member_names(group: dict[str, Any]) -> list[str | None]:
    return [m["display_name"] for m in group["members"]]
