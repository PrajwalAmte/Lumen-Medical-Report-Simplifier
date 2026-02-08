import time
import redis
from fastapi import HTTPException, status, Request
from app.core.config import settings

# Global Redis client for rate limiting
_redis_client = None


def get_redis_client():
    """Get Redis client instance for rate limiting operations."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True
        )
    return _redis_client


def rate_limit(request: Request):
    """Enforce per-minute rate limiting based on client IP address.
    
    CRITICAL BUG FIX: request.client can be None in test environments
    or when running behind certain proxies. This was causing AttributeError.
    
    Args:
        request: FastAPI request object
        
    Raises:
        HTTPException: 429 if rate limit exceeded
    """
    r = get_redis_client()
    
    # Handle cases where client info is not available
    if request.client is None:
        client_ip = "unknown"
    else:
        client_ip = request.client.host
    
    key = f"rate:{client_ip}"
    current = r.get(key)

    # Check if rate limit exceeded
    if current and int(current) >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )

    # Increment counter with atomic operations
    pipe = r.pipeline()
    pipe.incr(key, 1)  # Increment request count
    pipe.expire(key, 60)  # Set TTL of 60 seconds
    pipe.execute()
