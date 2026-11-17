"""The separate test database (<dev database name>_test), so dev data is never touched."""

import asyncio
from pathlib import Path

import asyncpg
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
_dev_url = make_url(Settings().database_url)
TEST_DATABASE_URL = _dev_url.set(database=f"{_dev_url.database}_test").render_as_string(
    hide_password=False
)


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


async def _ensure_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


def create_and_migrate() -> None:
    asyncio.run(_ensure_test_database())
    command.upgrade(alembic_config(), "head")
