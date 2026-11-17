"""Database test setup. Each test runs inside a transaction that is rolled back,
so tests can't affect each other."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from tests.support.database import TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _db(migrated_database: None) -> None:
    pass


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()
