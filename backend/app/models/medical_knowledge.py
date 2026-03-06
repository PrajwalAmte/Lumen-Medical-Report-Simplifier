"""Medical knowledge chunks stored with pgvector embeddings for RAG retrieval."""

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MedicalKnowledge(Base):
    __tablename__ = "medical_knowledge"
    __table_args__ = (
        Index("ix_mk_source", "source"),
        Index("ix_mk_entity_id", "entity_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(512), nullable=False)
    source = Column(String(50), nullable=False)      # catalog_tests | catalog_medicines
    entity_id = Column(String(100), nullable=True)    # test key or medicine key
    chunk_type = Column(String(30), nullable=True)    # factual | clinical
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
