from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models.job import Job
from app.core.config import settings
from app.core.constants import JOB_STATUS_EXPIRED
from app.core.logging import get_logger
from app.services.storage import delete_file

logger = get_logger("job_lifecycle")

JOB_EXPIRY_DAYS = settings.JOB_EXPIRY_DAYS
JOB_PURGE_DAYS = JOB_EXPIRY_DAYS * 2


def mark_expired_jobs(db: Session):
    expiry_date = datetime.now(timezone.utc) - timedelta(days=JOB_EXPIRY_DAYS)

    expired_jobs = db.query(Job).filter(
        Job.created_at < expiry_date,
        Job.status.in_(["completed", "failed"])
    ).all()

    for job in expired_jobs:
        job.status = JOB_STATUS_EXPIRED
        job.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
        logger.info(f"Marked {len(expired_jobs)} jobs as expired")
        return len(expired_jobs)
    except Exception as e:
        logger.error(f"Failed to mark jobs as expired: {e}")
        db.rollback()
        return 0


def delete_old_job_files(db: Session):
    expiry_date = datetime.now(timezone.utc) - timedelta(days=JOB_EXPIRY_DAYS)

    old_jobs = db.query(Job).filter(Job.created_at < expiry_date).all()
    deleted_count = 0

    for job in old_jobs:
        if job.file_path:
            try:
                delete_file(job.file_path)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete S3 object {job.file_path}: {e}")

    logger.info(f"Deleted {deleted_count} old job files")
    return deleted_count


def purge_expired_jobs(db: Session):
    purge_date = datetime.now(timezone.utc) - timedelta(days=JOB_PURGE_DAYS)

    old_expired = db.query(Job).filter(
        Job.status == JOB_STATUS_EXPIRED,
        Job.updated_at < purge_date
    ).all()

    for job in old_expired:
        db.delete(job)

    try:
        db.commit()
        logger.info(f"Purged {len(old_expired)} expired jobs")
        return len(old_expired)
    except Exception as e:
        logger.error(f"Failed to purge expired jobs: {e}")
        db.rollback()
        return 0


def cleanup_old_jobs(db: Session):
    logger.info("Starting job cleanup process")

    expired_count = mark_expired_jobs(db)
    deleted_count = delete_old_job_files(db)
    purged_count = purge_expired_jobs(db)

    logger.info(
        f"Cleanup complete: {expired_count} expired, "
        f"{deleted_count} files deleted, {purged_count} purged"
    )

    return {
        "expired_jobs": expired_count,
        "deleted_files": deleted_count,
        "purged_jobs": purged_count
    }
