from sqlalchemy import Column, String, Float, Boolean, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from app.db.base import Base


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(
        String,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Use native JSONB on PostgreSQL (supports GIN indexes, containment ops)
    # and fall back to generic JSON (TEXT-backed) on SQLite for local dev.
    result_json = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    confidence = Column(Float, default=0.0)
    processing_time = Column(Integer)
    llm_provider = Column(String)
    model = Column(String)
    cached = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
