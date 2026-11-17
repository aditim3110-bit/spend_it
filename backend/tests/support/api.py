"""Run the real API in tests against the test database and Redis database 15.

Codes are captured by a FakeSender instead of being sent. Rows created by a test are
deleted afterwards, and Redis database 15 is wiped before each test.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.main import create_app
from app.services.auth.otp import FakeSender
from tests.support.database import TEST_DATABASE_URL

TEST_REDIS_URL = "redis://localhost:6379/15"
PHONE = "+6591234567"
DEVICE = {"device_id": "test-iphone-1", "platform": "ios"}


@dataclass
class Api:
    client: httpx.AsyncClient
    sender: FakeSender
    settings: Settings

    async def send_code(self, value: str = PHONE, kind: str = "phone", **extra: Any):
        return await self.client.post(
            "/v1/auth/otp/send", json={"kind": kind, "value": value, **extra}
        )

    async def verify(
        self, value: str = PHONE, code: str | None = None, kind: str = "phone", **extra: Any
    ):
        body = {
            "kind": kind,
            "value": value,
            "code": code or self.sender.last_code(),
            "device": DEVICE,
            **extra,
        }
        return await self.client.post("/v1/auth/otp/verify", json=body)

    async def sign_in(self, value: str = PHONE, kind: str = "phone") -> dict[str, Any]:
        assert (await self.send_code(value, kind)).status_code == 202
        r = await self.verify(value, kind=kind)
        assert r.status_code == 200, r.text
        return r.json()

    async def headers(self, value: str = PHONE, *, key: bool = True) -> dict[str, str]:
        """Sign in and return headers for a signed-in change request."""
        session = await self.sign_in(value)
        h = {"Authorization": f"Bearer {session['access_token']}"}
        if key:
            h["Idempotency-Key"] = str(uuid.uuid4())
        return h


async def _cleanup() -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as c:
        for table in ("idempotency_keys", "refresh_tokens", "devices", "user_identifiers", "users"):
            await c.execute(text(f"DELETE FROM {table}"))
    await engine.dispose()


@asynccontextmanager
async def running_api(extra_router: APIRouter | None = None) -> AsyncIterator[Api]:
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()

    settings = Settings(env="test", database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    sender = FakeSender()
    app = create_app(settings, otp_sender=sender)
    if extra_router is not None:
        app.include_router(extra_router)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield Api(client=client, sender=sender, settings=settings)
    finally:
        await _cleanup()
