"""POST /v1/split/preview runs the same engine as saving, so every shared fixture must
come out identically through the API."""

from pathlib import Path

import pytest

from tests.split.fixtures import fixture_files, load
from tests.support.api import Api

SPLIT_CASES = [p for p in fixture_files() if load(p)["type"] == "split"]


async def auth(api: Api) -> dict[str, str]:
    return await api.headers(key=False)  # preview is exempt from retry tickets


async def test_preview_shows_who_owes_what(api: Api) -> None:
    r = await api.client.post(
        "/v1/split/preview",
        headers=await auth(api),
        json={
            "total": 10000,
            "currency": "SGD",
            "payers": [{"id": "ben", "amount": 10000}],
            "mode": "equal",
            "inputs": [{"id": "aditi"}, {"id": "ben"}, {"id": "chen"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert [(s["id"], s["owed"]) for s in body["shares"]] == [
        ("aditi", 3333),
        ("ben", 3334),
        ("chen", 3333),
    ]
    nets = {n["id"]: n["net"] for n in body["nets"]}
    assert nets == {"ben": 6666, "aditi": -3333, "chen": -3333}  # others owe Ben 66.66


async def test_split_errors_are_problem_details_with_the_offending_person(api: Api) -> None:
    r = await api.client.post(
        "/v1/split/preview",
        headers=await auth(api),
        json={
            "total": 10000,
            "currency": "SGD",
            "payers": [{"id": "aditi", "amount": 10000}],
            "mode": "percent",
            "inputs": [
                {"id": "aditi", "value": 3333},
                {"id": "ben", "value": 3333},
                {"id": "chen", "value": 3333},
            ],
        },
    )
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"].endswith("/percent-sum-invalid")
    assert body["errors"] == [{"code": "PercentSumInvalid", "remainder": 1}]


async def test_preview_requires_sign_in(api: Api) -> None:
    r = await api.client.post("/v1/split/preview", json={})
    assert r.status_code in (401, 422)
    r = await api.client.post(
        "/v1/split/preview",
        json={"total": 1, "currency": "SGD", "payers": [], "mode": "equal", "inputs": []},
    )
    assert r.status_code == 401


async def test_missing_value_in_exact_mode_is_a_clear_error(api: Api) -> None:
    r = await api.client.post(
        "/v1/split/preview",
        headers=await auth(api),
        json={
            "total": 100,
            "currency": "SGD",
            "payers": [{"id": "aditi", "amount": 100}],
            "mode": "exact",
            "inputs": [{"id": "aditi"}],
        },
    )
    assert r.status_code == 422


@pytest.mark.parametrize("path", SPLIT_CASES, ids=lambda p: p.stem)
async def test_every_fixture_through_the_api(api: Api, path: Path) -> None:
    case = load(path)
    r = await api.client.post(
        "/v1/split/preview",
        headers=await auth(api),
        json={k: case[k] for k in ("total", "currency", "payers", "mode", "inputs")},
    )
    if "expect_error" in case:
        assert r.status_code == 422, r.text
        assert r.json()["errors"] == [case["expect_error"]]
    else:
        assert r.status_code == 200, r.text
        got = {s["id"]: s["owed"] for s in r.json()["shares"]}
        assert got == {s["id"]: s["owed"] for s in case["expect"]["shares"]}
