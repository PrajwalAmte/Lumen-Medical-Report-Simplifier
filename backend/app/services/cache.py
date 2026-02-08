import redis
import json
from app.core.config import settings
from app.core.logging import get_logger
from app.services.result_sanitizer import sanitize_result

logger = get_logger("cache")

# Global Redis client for caching operations
_redis_client = None


def get_redis_client():
    """Get Redis client instance for caching operations."""
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True  # Automatically decode bytes to strings
        )

    return _redis_client


def get_cached_result(job_id: str) -> dict | None:
    """Retrieve cached result for a job.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        dict: Cached result data or None if not found
    """
    try:
        r = get_redis_client()
        key = f"result:{job_id}"
        value = r.get(key)
        if value:
            logger.info(f"Cache hit for job {job_id}")
            parsed = json.loads(value)
            # Attempt to sanitize cached data, fall back to raw if sanitization fails
            try:
                return sanitize_result(parsed)
            except Exception:
                # Return unsanitized data rather than failing completely
                return parsed
        return None
    except Exception as e:
        logger.error(f"Cache get failed: {e}")
        return None


def set_cached_result(job_id: str, result: dict, ttl_sec: int = 60 * 60 * 24 * 7):
    try:
        r = get_redis_client()
        key = f"result:{job_id}"
        try:
            safe = sanitize_result(result)
        except Exception:
            safe = result
        r.setex(key, ttl_sec, json.dumps(safe))
        logger.info(f"Cached result for job {job_id}")
    except Exception as e:
        logger.error(f"Cache set failed: {e}")
