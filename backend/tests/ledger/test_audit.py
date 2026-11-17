"""The nightly ledger audit (app/jobs/audit.py)."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.jobs.audit import run_audit
from tests.support.api import Api
from tests.support.database import TEST_DATABASE_URL
from tests.support.people import befriend, equal_split, person


async def audit(**kwargs):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await run_audit(session, **kwargs)
    finally:
        await engine.dispose()


async def _setup(api: Api):
    aditi = await person(api, "+6591111111", "Aditi")
    ben = await person(api, "+6592222222", "Ben")
    await befriend(api, aditi, ben)
    r = await api.client.post(
        "/v1/expenses", json=equal_split(aditi, [aditi, ben], 1000), headers=aditi.write()
    )
    assert r.status_code == 201
    return aditi, ben


async def test_clean_ledger_reports_nothing(api: Api) -> None:
    await _setup(api)
    report = await audit()
    assert report.clean
    assert not report.repaired


async def test_wrong_balance_is_reported_and_repaired(api: Api, db_execute) -> None:
    aditi, ben = await _setup(api)
    await db_execute("UPDATE balances SET amount_minor = amount_minor + 77")

    dry = await audit(repair=False)
    assert not dry.clean
    assert not dry.repaired
    [(stored, correct)] = dry.balance_differences.values()
    assert abs(stored - correct) == 77

    fixed = await audit()
    assert fixed.repaired
    assert (await audit()).clean
    b = (await api.client.get("/v1/balances", headers=aditi.auth)).json()
    assert b["people"][0]["amounts"] == [{"currency": "SGD", "amount_minor": 500}]
    assert ben


async def test_missing_rows_are_rebuilt(api: Api, db_execute) -> None:
    """E.g. expenses saved before the balances table existed."""
    aditi, _ = await _setup(api)
    await db_execute("DELETE FROM balances")
    assert (await audit()).repaired
    b = (await api.client.get("/v1/balances", headers=aditi.auth)).json()
    assert b["totals"] == [{"currency": "SGD", "owed_to_you": 500, "you_owe": 0}]


async def test_unbalanced_revision_is_reported(api: Api, db_execute) -> None:
    """Can't happen through the app (the engine and the append-only trigger prevent it),
    so we switch the trigger off just for this test to simulate a corrupted ledger."""
    await _setup(api)
    await db_execute(
        "DO $$ BEGIN PERFORM set_config('session_replication_role', 'replica', true); "
        "UPDATE expense_shares SET owed_minor = 1; END $$"
    )
    report = await audit()
    assert len(report.unbalanced_revisions) == 1
    assert not report.clean
    assert not report.repaired  # a person must look at a damaged ledger first
