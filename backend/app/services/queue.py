from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_client import get_redis_client

logger = get_logger("queue")

# Queue size limits to prevent memory issues
MAX_QUEUE_SIZE = 1000
QUEUE_SIZE_CHECK_INTERVAL = 100


def push_job(job_id: str):
    """Add job to the processing queue with size limit check.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        bool: True if job was queued successfully, False otherwise
    """
    try:
        r = get_redis_client()

        # Check queue size to prevent memory overflow
        current_queue_size = r.llen(settings.QUEUE_NAME)

        if current_queue_size >= MAX_QUEUE_SIZE:
            logger.error(f"Queue is full (size: {current_queue_size}). Rejecting job {job_id}")
            return False

        # Add job to left side of queue (LPUSH + BRPOP = FIFO)
        r.lpush(settings.QUEUE_NAME, job_id)
        logger.info(f"Queued job {job_id} (queue size: {current_queue_size + 1})")
        return True
    except Exception as e:
        logger.error(f"Redis push failed: {e}")
        return False


def pop_job(block_timeout: int = 10) -> str | None:
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


def get_queue_size() -> int:
    try:
        r = get_redis_client()
        return r.llen(settings.QUEUE_NAME)
    except Exception as e:
        logger.error(f"Failed to get queue size: {e}")
        return -1
