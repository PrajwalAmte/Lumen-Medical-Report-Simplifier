from sqlalchemy import Column, String, Float, Boolean, Integer, Text, DateTime
from datetime import datetime
from app.db.base import Base


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, index=True, nullable=False)
    result_json = Column(Text, nullable=False)
    confidence = Column(Float, default=0.0)
    processing_time = Column(Integer)
    llm_provider = Column(String)
    model = Column(String)
    cached = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
