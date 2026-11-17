"""Simple per-hour limits in Redis ("at most N of these per hour").

Fixed one-hour window starting at the first request, the common approach for low-volume
actions like sending codes or adding friends.
"""

from redis.asyncio import Redis

from app.core.errors import ProblemError


async def hit(redis: Redis, key: str, limit: int, window_seconds: int, detail: str) -> None:
    """Count one action; raise 429 with a Retry-After header once over the limit."""
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)  # window starts at the first request
        pipe.ttl(key)
        count, _, ttl = await pipe.execute()
    if count > limit:
        raise ProblemError(
            429,
            "too-many-requests",
            detail,
            headers={"Retry-After": str(max(int(ttl), 1))},
        )
