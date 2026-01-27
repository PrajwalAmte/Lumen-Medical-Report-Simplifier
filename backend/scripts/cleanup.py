import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db.session import SessionLocal
from app.services.job_lifecycle import cleanup_old_jobs
from app.core.logging import setup_logging, get_logger

setup_logging()
logger = get_logger("cleanup")


def run():
    db = SessionLocal()
    try:
        logger.info("Starting scheduled job cleanup")
        result = cleanup_old_jobs(db)
        logger.info(f"Cleanup completed: {result}")
        return True
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
