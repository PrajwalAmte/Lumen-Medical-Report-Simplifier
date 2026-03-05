from fastapi import HTTPException, status, Request
from app.core.config import settings
from app.services.redis_client import get_redis_client

# Lua script for atomic increment-and-check rate limiting.
# Eliminates the TOCTOU race between reading the counter and incrementing it.
# Returns the new count after increment. Sets TTL only on the first request
# in a window (when INCR returns 1) to avoid resetting the expiry mid-window.
_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


def rate_limit(request: Request):
    """Enforce per-minute rate limiting based on client IP address.
    
    Uses an atomic Lua script to increment the counter and check the limit
    in a single Redis round-trip, preventing race conditions where concurrent
    requests could bypass the limit.
    
    Args:
        request: FastAPI request object
        
    Raises:
        HTTPException: 429 if rate limit exceeded
    """
    r = get_redis_client()

    # Handle cases where client info is not available
    client_ip = request.client.host if request.client else "unknown"

    key = f"rate:{client_ip}"
    window_seconds = 60

    # Atomic increment-then-check: no window for concurrent bypass
    current_count = r.eval(_RATE_LIMIT_LUA, 1, key, window_seconds)

    if int(current_count) > settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
