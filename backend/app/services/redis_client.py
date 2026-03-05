"""
Shared Redis client singleton.

Every service that needs Redis (cache, queue, rate-limiter) MUST import
`get_redis_client` from this module instead of creating its own connection.
This guarantees a single connection-pool for the entire process and makes
it trivial to swap the implementation (e.g. cluster, sentinel) later.
"""

import redis
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("redis")

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Return the shared Redis client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        logger.info("Shared Redis client initialised")
    return _redis_client
