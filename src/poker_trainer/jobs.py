"""Lazy singleton arq Redis pool for enqueueing background jobs from the API.

Mirrors shared_services.llm.get_client()'s lazy-singleton pattern.
"""

from __future__ import annotations

import os

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")

_pool: ArqRedis | None = None


async def get_redis_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _pool
