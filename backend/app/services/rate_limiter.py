from fastapi import HTTPException, status, Request
from app.core.config import settings
from app.services.redis_client import get_redis_client

# Atomic Lua script: increments the per-IP counter and sets a 60s TTL on
# the first request in each window, avoiding a TOCTOU race condition.
_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


def rate_limit(request: Request):
    """Raise 429 if the requesting IP has exceeded RATE_LIMIT_PER_MINUTE."""
    r = get_redis_client()
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate:{client_ip}"
    window_seconds = 60

    current_count = r.eval(_RATE_LIMIT_LUA, 1, key, window_seconds)

    if int(current_count) > settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
