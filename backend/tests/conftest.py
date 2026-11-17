"""Shared test helpers.

Tests talk to the real Postgres and Redis from docker compose, so start them first:
    docker compose up -d db redis
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from tests.support.database import create_and_migrate

AppClient = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def make_client() -> AppClient:
    """Build an app (optionally with overridden settings) and an HTTP client for it."""

    @asynccontextmanager
    async def _make(**overrides: object) -> AsyncIterator[httpx.AsyncClient]:
        settings = Settings(env="test", **overrides)  # type: ignore[arg-type]
        app = create_app(settings)
        # Run startup/shutdown so connection pools exist during the test.
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                yield c

    return _make


@pytest.fixture
async def client(make_client: AppClient) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client() as c:
        yield c


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Create the test database if needed and bring it to the latest schema (once per run)."""
    create_and_migrate()
