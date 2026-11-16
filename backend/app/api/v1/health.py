"""Health checks.

/v1/health        "is the API process up?"  (no dependencies; used by load balancers)
/v1/health/ready  "can it do real work?"    (checks Postgres and Redis)
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.core.errors import ProblemError

router = APIRouter(prefix="/health", tags=["health"])


class HealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


@router.get("", response_model=HealthOut)
async def liveness() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/ready", response_model=HealthOut)
async def readiness(request: Request) -> HealthOut:
    failed: list[dict[str, str]] = []

    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        failed.append({"component": "database", "msg": "unreachable"})

    try:
        await request.app.state.redis.ping()
    except Exception:
        failed.append({"component": "redis", "msg": "unreachable"})

    if failed:
        raise ProblemError(503, "dependency-unavailable", "A required service is down.", failed)
    return HealthOut(status="ok")
