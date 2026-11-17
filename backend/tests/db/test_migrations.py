"""The migration matches the models, runs both ways, and uses integer money only."""

import asyncio

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.models import Base
from tests.support.database import TEST_DATABASE_URL, alembic_config


def test_downgrade_then_upgrade_round_trip() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def _diff() -> list:
    async def run() -> list:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.connect() as c:
            diff = await c.run_sync(
                lambda sync: compare_metadata(
                    MigrationContext.configure(sync, opts={"compare_type": True}), Base.metadata
                )
            )
        await engine.dispose()
        return diff

    return asyncio.run(run())


def test_models_and_migrations_match() -> None:
    """If this fails, someone changed a model without writing a migration (or vice versa)."""
    assert _diff() == []


def _columns(sql: str) -> list:
    async def run() -> list:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.connect() as c:
            rows = (await c.execute(text(sql))).all()
        await engine.dispose()
        return [tuple(r) for r in rows]

    return asyncio.run(run())


def test_no_float_or_decimal_columns_anywhere() -> None:
    """CLAUDE.md rule 1: money is integers. No float/numeric column may exist at all."""
    assert (
        _columns(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type IN ('numeric', 'real', 'double precision')"
        )
        == []
    )


def test_money_columns_are_bigint() -> None:
    rows = _columns(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name LIKE '%\\_minor' ESCAPE '\\'"
    )
    assert rows, "expected some *_minor columns"
    assert {r[2] for r in rows} == {"bigint"}, rows
