"""
Shared pytest fixtures for the Lumen backend test suite.

IMPORTANT: We do NOT import app.main at module level because that would
trigger the production database engine (psycopg2 / PostgreSQL).
Instead we build lightweight fixtures from first principles.
"""

import sys
import os

# Ensure the backend root is on sys.path so `app.*` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set a dummy DATABASE_URL BEFORE any app module is imported so that
# Settings() never tries to connect to PostgreSQL.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("REQUIRE_API_KEY", "false")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("STORAGE_TYPE", "local")

import pytest
from unittest.mock import Mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_session(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def mock_redis():
    return Mock()


@pytest.fixture
def sample_job_data():
    return {
        "id": "test_job_123",
        "file_path": "uploads/test.pdf",
        "locale": "en-IN",
        "context": "auto",
        "status": "queued",
        "stage": "uploading",
        "progress": 5,
    }
