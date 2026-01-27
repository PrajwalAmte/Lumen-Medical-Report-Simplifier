from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.db.session import SessionLocal
from app.services.job_lifecycle import cleanup_old_jobs
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger("scheduler")

scheduler = BackgroundScheduler()


def run_cleanup_job():
    logger.info("Running scheduled cleanup job")

    db = SessionLocal()
    try:
        result = cleanup_old_jobs(db)
        logger.info(f"Cleanup result: {result}")
    except Exception as e:
        logger.error(f"Scheduled cleanup failed: {e}", exc_info=True)
    finally:
        db.close()


def start_scheduler():
    logger.info("Starting background scheduler")

    scheduler.add_job(
        run_cleanup_job,
        trigger=IntervalTrigger(hours=settings.CLEANUP_INTERVAL_HOURS),
        id="daily_cleanup",
        name="Daily cleanup job",
        replace_existing=True,
    )

    scheduler.start()