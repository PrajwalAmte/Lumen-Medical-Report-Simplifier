from sqlalchemy import Column, String, Integer, DateTime, Text, Index
from datetime import datetime, timezone
from app.db.base import Base


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Composite index for the common query pattern:
        # "SELECT … WHERE status IN (…) AND created_at < …"
        # Used by job_lifecycle.mark_expired_jobs / delete_old_job_files.
        Index("ix_jobs_status_created_at", "status", "created_at"),
    )

    id = Column(String, primary_key=True, index=True)
    file_path = Column(String, nullable=False)
    locale = Column(String, default="en-IN")
    context = Column(String, default="auto")
    status = Column(String, default="queued")
    stage = Column(String, default="uploading")
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
