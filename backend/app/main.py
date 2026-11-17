"""Entry point. `create_app()` builds the API; `app` is what `fastapi dev` runs.

Using a factory (instead of one global app) lets tests build an app with their
own settings, e.g. pointing at a broken Redis to test the 503 path.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.v1 import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.idempotency import IdempotencyMiddleware
from app.db.session import make_engine, make_sessionmaker
from app.services.auth.otp import ConsoleSender, OtpSender
from app.web.routes import router as web_router


def create_app(settings: Settings | None = None, otp_sender: OtpSender | None = None) -> FastAPI:
    """`otp_sender` lets tests capture codes. Real SMS/email senders replace ConsoleSender
    once the Twilio and email accounts exist."""
    settings = settings or get_settings()
    sender = otp_sender or ConsoleSender()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Startup: open connection pools once and share them across requests.
        app.state.settings = settings
        app.state.engine = make_engine(settings.database_url)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        app.state.redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        app.state.otp_sender = sender
        yield
        # Shutdown: close them cleanly.
        await app.state.redis.aclose()
        await app.state.engine.dispose()

    app = FastAPI(title="SpendIt API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(IdempotencyMiddleware)
    app.include_router(v1_router)
    app.include_router(web_router)
    return app


app = create_app()
