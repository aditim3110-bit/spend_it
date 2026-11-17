"""Checks the fixture files themselves (not the engine).

These catch typos in hand-written cases: wrong shape, totals that don't add up,
or an expected share for someone who isn't splitting.
"""

import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.split.fixtures import SCHEMA_PATH, fixture_files, load

FILES = fixture_files()
VALIDATOR = Draft202012Validator(load(SCHEMA_PATH))


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(load(SCHEMA_PATH))


def test_enough_cases() -> None:
    assert len(FILES) >= 25


def test_filenames_are_numbered_and_unique() -> None:
    numbers = [f.name[:3] for f in FILES]
    assert all(re.fullmatch(r"\d{3}_[a-z0-9_]+\.json", f.name) for f in FILES)
    assert len(numbers) == len(set(numbers))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_fixture_matches_schema(path: Path) -> None:
    errors = [e.message for e in VALIDATOR.iter_errors(load(path))]
    assert errors == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_expected_results_balance(path: Path) -> None:
    case = load(path)
    expect = case.get("expect")
    if expect is None:
        return  # error cases have nothing to balance
    payers = expect.get("payers", case.get("payers"))
    inputs = expect.get("inputs", case.get("inputs"))
    shares = expect["shares"]

    # Rule 3 in CLAUDE.md: paid total == owed total == expense total.
    assert sum(p["amount"] for p in payers) == case["total"]
    assert sum(s["owed"] for s in shares) == case["total"]
    # Every participant gets exactly one result row, zero rows included.
    assert sorted(s["id"] for s in shares) == sorted(i["id"] for i in inputs)
