import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import Mock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.main import create_app
from app.db.base import Base
from app.core.config import Settings


@pytest.fixture(scope="session")
def test_settings():
    return Settings(
        DATABASE_URL="sqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/1",
        REQUIRE_API_KEY=False,
        LOG_LEVEL="DEBUG",
        OPENAI_API_KEY="test-key"
    )


@pytest.fixture(scope="session")
def test_engine(test_settings):
    engine = create_engine(test_settings.DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_session(test_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_client():
    from fastapi import FastAPI
    from app.api.routes.upload import router as upload_router
    from app.api.routes.status import router as status_router
    from app.api.routes.result_routes import router as result_router
    
    app = FastAPI()
    
    @app.get("/health")
    def health():
        return {"status": "ok", "app": "Lumen"}
    
    app.include_router(upload_router)
    app.include_router(status_router)
    app.include_router(result_router)
    
    return TestClient(app)


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
        "progress": 5
    }