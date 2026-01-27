from sqlalchemy import Column, String, Integer, DateTime, Text
from datetime import datetime
from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    file_path = Column(String, nullable=False)
    locale = Column(String, default="en-IN")
    context = Column(String, default="auto")
    status = Column(String, default="queued")
    stage = Column(String, default="uploading")
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
