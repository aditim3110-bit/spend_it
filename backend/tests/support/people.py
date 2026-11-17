"""Helpers for tests that need several signed-in people who are friends."""

import uuid
from dataclasses import dataclass
from typing import Any

from tests.support.api import Api


@dataclass
class Person:
    id: str
    name: str | None
    phone: str
    auth: dict[str, str]  # Authorization header only

    def write(self, **extra: str) -> dict[str, str]:
        """Headers for a change request, with a fresh retry ticket."""
        return {**self.auth, "Idempotency-Key": str(uuid.uuid4()), **extra}


async def person(api: Api, phone: str, name: str | None) -> Person:
    session = await api.sign_in(phone)
    auth = {"Authorization": f"Bearer {session['access_token']}"}
    me = await api.client.get("/v1/me", headers=auth)
    p = Person(id=me.json()["id"], name=None, phone=phone, auth=auth)
    if name:
        r = await api.client.patch("/v1/me", json={"display_name": name}, headers=p.write())
        assert r.status_code == 200, r.text
        p.name = name
    return p


async def befriend(api: Api, a: Person, b: Person) -> None:
    r = await api.client.post(
        "/v1/friends/add", json={"kind": "phone", "value": b.phone}, headers=a.write()
    )
    assert r.status_code == 200, r.text


def equal_split(
    payer: Person, people: list[Person], amount: int, currency: str = "SGD", **extra: Any
) -> dict[str, Any]:
    """ "<payer> paid <amount>, split equally between <people>"."""
    return {
        "name": "Dinner",
        "amount_minor": amount,
        "currency": currency,
        "expense_date": "2026-11-17",
        "payers": [{"user_id": payer.id, "amount_minor": amount}],
        "split": {"mode": "equal", "shares": [{"user_id": p.id} for p in people]},
        **extra,
    }


def owed(expense: dict[str, Any]) -> dict[str | None, int]:
    """{name: owed_minor} for an expense response."""
    return {s["display_name"]: s["owed_minor"] for s in expense["shares"]}
