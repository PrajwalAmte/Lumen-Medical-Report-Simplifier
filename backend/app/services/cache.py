import json
from typing import Optional
from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_client import get_redis_client
from app.services.result_sanitizer import sanitize_result

logger = get_logger("cache")


def get_cached_result(job_id: str) -> Optional[dict]:
    """Return the cached result for a job, or None if not found."""
    try:
        r = get_redis_client()
        key = f"result:{job_id}"
        value = r.get(key)
        if value:
            logger.info(f"Cache hit for job {job_id}")
            parsed = json.loads(value)
            try:
                return sanitize_result(parsed)
            except Exception:
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
