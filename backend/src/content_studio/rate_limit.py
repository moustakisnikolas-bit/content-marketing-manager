import time
from dataclasses import dataclass

import redis.asyncio as redis

# Redis's first real use in this codebase — strictly cache/coordination,
# per the hard architecture rule (PostgreSQL is the sole authoritative
# store). A fixed-window counter is deliberately simple: it can allow a
# short burst right at a window boundary, which is an acceptable tradeoff
# for a public-API courtesy limit, not a billing-critical control (that's
# what the credit ledger in modules/billing is for).

DEFAULT_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class RateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def check_and_increment(
        self, key: str, *, limit: int, window_seconds: int = DEFAULT_WINDOW_SECONDS
    ) -> RateLimitResult:
        window = int(time.time() // window_seconds)
        redis_key = f"ratelimit:{key}:{window}"
        count = await self._client.incr(redis_key)
        if count == 1:
            await self._client.expire(redis_key, window_seconds)
        reset_seconds = window_seconds - int(time.time() % window_seconds)
        return RateLimitResult(
            allowed=count <= limit, limit=limit, remaining=max(0, limit - count), reset_seconds=reset_seconds,
        )


_redis_client: redis.Redis | None = None


def get_redis_client(redis_url: str) -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client
