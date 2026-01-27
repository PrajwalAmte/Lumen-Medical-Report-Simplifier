import time
import redis
from fastapi import HTTPException, status, Request
from app.core.config import settings

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True
        )
    return _redis_client


def rate_limit(request: Request):
    r = get_redis_client()
    key = f"rate:{request.client.host}"
    current = r.get(key)

    if current and int(current) >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )

    pipe = r.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 60)
    pipe.execute()
