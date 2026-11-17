"""Retry tickets (Idempotency-Key): a repeated change is done once, and replayed after."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser
from app.core.idempotency import idempotency_key_header
from app.main import create_app
from tests.support.api import Api, running_api


class Counter:
    """A test-only route that counts how many times it actually ran."""

    def __init__(self) -> None:
        self.runs = 0
        self.fail_next = False
        self.release = asyncio.Event()
        self.release.set()
        self.router = APIRouter(prefix="/v1/test")

        @self.router.post("/count", status_code=201)
        async def count(
            body: dict,
            _: CurrentUser,
            __: Annotated[uuid.UUID, Depends(idempotency_key_header)],
        ) -> dict:
            await self.release.wait()
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("simulated crash")
            self.runs += 1
            return {"run": self.runs, "echo": body}

        @self.router.delete("/thing", status_code=204)
        async def delete_thing(
            _: CurrentUser, __: Annotated[uuid.UUID, Depends(idempotency_key_header)]
        ) -> Response:
            self.runs += 1
            return Response(status_code=204)


@pytest.fixture
async def counter_api(migrated_database: None) -> AsyncIterator[tuple[Api, Counter]]:
    counter = Counter()
    async with running_api(counter.router) as api:
        yield api, counter


async def test_retry_with_same_key_is_replayed_not_redone(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers()
    first = await api.client.post("/v1/test/count", json={"a": 1}, headers=h)
    retry = await api.client.post("/v1/test/count", json={"a": 1}, headers=h)
    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json() == {"run": 1, "echo": {"a": 1}}
    assert retry.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert counter.runs == 1  # the work happened once


async def test_new_key_does_the_work_again(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers()
    await api.client.post("/v1/test/count", json={}, headers=h)
    h2 = {**h, "Idempotency-Key": str(uuid.uuid4())}
    r = await api.client.post("/v1/test/count", json={}, headers=h2)
    assert r.json()["run"] == 2
    assert counter.runs == 2


async def test_missing_key_is_rejected(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers(key=False)
    r = await api.client.post("/v1/test/count", json={}, headers=h)
    assert r.status_code == 400
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["type"].endswith("/idempotency-key-required")
    assert counter.runs == 0


async def test_key_must_be_a_uuid(counter_api) -> None:
    api, _ = counter_api
    h = {**(await api.headers()), "Idempotency-Key": "not-a-uuid"}
    r = await api.client.post("/v1/test/count", json={}, headers=h)
    assert r.status_code == 400
    assert r.json()["type"].endswith("/invalid-idempotency-key")


async def test_same_key_with_different_body_is_rejected(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers()
    await api.client.post("/v1/test/count", json={"amount": 100}, headers=h)
    r = await api.client.post("/v1/test/count", json={"amount": 999}, headers=h)
    assert r.status_code == 422
    assert r.json()["type"].endswith("/idempotency-key-reused")
    assert counter.runs == 1


async def test_retry_while_first_is_still_running_gets_409(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers()
    counter.release.clear()  # hold the first request inside the route
    first = asyncio.create_task(api.client.post("/v1/test/count", json={}, headers=h))
    await asyncio.sleep(0.2)
    second = await api.client.post("/v1/test/count", json={}, headers=h)
    assert second.status_code == 409
    assert second.json()["type"].endswith("/request-in-progress")
    assert second.headers["retry-after"] == "1"
    counter.release.set()
    assert (await first).status_code == 201
    assert counter.runs == 1


async def test_server_error_is_not_saved_so_retry_runs_again(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers()
    counter.fail_next = True
    crashed = await api.client.post("/v1/test/count", json={}, headers=h)
    assert crashed.status_code == 500
    retry = await api.client.post("/v1/test/count", json={}, headers=h)
    assert retry.status_code == 201
    assert "idempotent-replayed" not in retry.headers
    assert counter.runs == 1


async def test_expired_key_can_be_used_again(counter_api, db_execute) -> None:
    api, counter = counter_api
    h = await api.headers()
    await api.client.post("/v1/test/count", json={}, headers=h)
    await db_execute("UPDATE idempotency_keys SET expires_at = now() - interval '1 second'")
    r = await api.client.post("/v1/test/count", json={}, headers=h)
    assert r.json()["run"] == 2
    assert counter.runs == 2


async def test_keys_are_per_user(counter_api) -> None:
    api, counter = counter_api
    key = str(uuid.uuid4())
    aditi = {**(await api.headers("+6591234567")), "Idempotency-Key": key}
    ben = {**(await api.headers("+6598765432")), "Idempotency-Key": key}
    await api.client.post("/v1/test/count", json={}, headers=aditi)
    r = await api.client.post("/v1/test/count", json={}, headers=ben)
    assert "idempotent-replayed" not in r.headers
    assert counter.runs == 2


async def test_empty_204_response_is_replayed(counter_api) -> None:
    api, counter = counter_api
    h = await api.headers()
    first = await api.client.delete("/v1/test/thing", headers=h)
    retry = await api.client.delete("/v1/test/thing", headers=h)
    assert first.status_code == retry.status_code == 204
    assert retry.headers["idempotent-replayed"] == "true"
    assert counter.runs == 1


async def test_signed_out_change_gets_401_not_a_key_error(counter_api) -> None:
    api, _ = counter_api
    r = await api.client.post("/v1/test/count", json={})
    assert r.status_code == 401


async def test_sign_in_and_reads_need_no_key(api: Api) -> None:
    session = await api.sign_in()  # POSTs to /v1/auth/* without a key
    r = await api.client.get(
        "/v1/me", headers={"Authorization": f"Bearer {session['access_token']}"}
    )
    assert r.status_code == 200


def test_every_change_route_declares_the_header_in_the_contract() -> None:
    """The OpenAPI spec is the contract the Swift client is generated from (CLAUDE.md
    rule 7). Every route that needs a key must say so there."""
    spec = create_app().openapi()
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
                continue
            if path.startswith("/v1/auth/") or path == "/v1/split/preview":
                continue
            names = {p["name"] for p in op.get("parameters", []) if p["in"] == "header"}
            if "Idempotency-Key" not in names:
                missing.append(f"{method.upper()} {path}")
    assert missing == []
