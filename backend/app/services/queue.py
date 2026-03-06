from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_client import get_redis_client

logger = get_logger("queue")

MAX_QUEUE_SIZE = 1000
QUEUE_SIZE_CHECK_INTERVAL = 100


def push_job(job_id: str):
    """Push a job onto the Redis queue. Returns False if the queue is full."""
    try:
        r = get_redis_client()
        current_queue_size = r.llen(settings.QUEUE_NAME)

        if current_queue_size >= MAX_QUEUE_SIZE:
            logger.error(f"Queue is full (size: {current_queue_size}). Rejecting job {job_id}")
            return False

        r.lpush(settings.QUEUE_NAME, job_id)  # LPUSH + BRPOP = FIFO
        logger.info(f"Queued job {job_id} (queue size: {current_queue_size + 1})")
        return True
    except Exception as e:
        logger.error(f"Redis push failed: {e}")
        return False


def pop_job(block_timeout: int = 10):
    try:
        r = get_redis_client()
        result = r.brpop(settings.QUEUE_NAME, timeout=block_timeout)

        if result:
            _, job_id = result
            logger.info(f"Popped job {job_id} from queue")
            return job_id

        return None

    except Exception as e:
        logger.error(f"Redis pop failed: {e}")
        return None



