"""Runs the engine against every shared fixture in fixtures/split/."""

from pathlib import Path
from typing import Any

import pytest

from app.services.split_engine import (
    Payer,
    ShareInput,
    SplitError,
    SplitMode,
    SplitRequest,
    TwoPersonShortcut,
    compute_split,
    two_person,
)
from tests.split.fixtures import fixture_files, load


def _payers(raw: list[dict[str, Any]]) -> tuple[Payer, ...]:
    return tuple(Payer(p["id"], p["amount"]) for p in raw)


def _inputs(raw: list[dict[str, Any]]) -> tuple[ShareInput, ...]:
    return tuple(ShareInput(i["id"], i.get("value")) for i in raw)


def _owed(result_shares: Any) -> dict[str, int]:
    return {s.id: s.owed for s in result_shares}


@pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.stem)
def test_fixture(path: Path) -> None:
    case = load(path)

    if case["type"] == "shortcut":
        exp = case["expect"]
        req = two_person(
            TwoPersonShortcut(case["shortcut"]),
            case["you"],
            case["other"],
            case["total"],
            case["currency"],
        )
        # The shortcut must build exactly the general split described in the fixture...
        assert req.mode == SplitMode(exp["mode"])
        assert req.payers == _payers(exp["payers"])
        assert req.inputs == _inputs(exp["inputs"])
        # ...and the engine must then produce the expected shares.
        assert _owed(compute_split(req).shares) == {s["id"]: s["owed"] for s in exp["shares"]}
        return

    req = SplitRequest(
        total=case["total"],
        currency=case["currency"],
        payers=_payers(case["payers"]),
        mode=SplitMode(case["mode"]),
        inputs=_inputs(case["inputs"]),
    )

    if "expect_error" in case:
        want = case["expect_error"]
        with pytest.raises(SplitError) as info:
            compute_split(req)
        err = info.value
        got = {
            "code": err.code,
            "side": err.side,
            "participant_id": err.participant_id,
            "remainder": err.remainder,
        }
        # Exactly the fields the fixture lists: no missing details, no extra ones.
        assert {k: v for k, v in got.items() if v is not None} == want
        return

    result = compute_split(req)
    assert _owed(result.shares) == {s["id"]: s["owed"] for s in case["expect"]["shares"]}
    # Output keeps the input order, so the app can show people in the order they were added.
    assert [s.id for s in result.shares] == [i["id"] for i in case["inputs"]]
