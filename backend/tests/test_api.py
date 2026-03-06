"""
Tests for API route handlers — upload, status, result.

Uses a proper test DB injected via FastAPI dependency overrides
so routes see the same SQLite test database as the fixture.
"""

import io
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.api.deps import get_db
from app.api.routes.upload import router as upload_router
from app.api.routes.status import router as status_router
from app.api.routes.result_routes import router as result_router
from app.models.job import Job
from app.models.result import Result
from app.core.constants import JOB_STATUS_QUEUED, STAGE_UPLOADING


# ---- fixtures ----

@pytest.fixture(scope="module")
def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(_engine):
    Session = sessionmaker(bind=_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db_session):
    """TestClient with test-DB injected via dependency override."""
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(upload_router)
    app.include_router(status_router)
    app.include_router(result_router)

    # Override DB dependency
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---- health ----

def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---- status ----

def test_status_job_not_found(client):
    resp = client.get("/status/nonexistent")
    assert resp.status_code == 404


def test_status_happy_path(client, db_session):
    job = Job(
        id="status_test_1",
        file_path="uploads/test.pdf",
        locale="en-IN",
        context="auto",
        status=JOB_STATUS_QUEUED,
        stage=STAGE_UPLOADING,
        progress=5,
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get("/status/status_test_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "status_test_1"
    assert data["status"] == JOB_STATUS_QUEUED
    assert data["progress"] == 5


def test_status_expired_job(client, db_session):
    job = Job(
        id="expired_job",
        file_path="uploads/old.pdf",
        status="expired",
        stage="done",
        progress=100,
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get("/status/expired_job")
    assert resp.status_code == 410


# ---- result ----

def test_result_not_found(client):
    resp = client.get("/result/nonexistent")
    assert resp.status_code == 404


def test_result_not_completed(client, db_session):
    job = Job(
        id="processing_job",
        file_path="uploads/test.pdf",
        status="processing",
        stage="ocr",
        progress=50,
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get("/result/processing_job")
    assert resp.status_code == 202


def test_result_failed_job(client, db_session):
    job = Job(
        id="failed_job",
        file_path="uploads/test.pdf",
        status="failed",
        stage="done",
        progress=0,
        error_message="OCR failure",
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get("/result/failed_job")
    assert resp.status_code == 400
    assert "OCR failure" in resp.json()["detail"]


@patch("app.api.routes.result_routes.get_cached_result")
def test_result_from_cache(mock_cache, client, db_session):
    job = Job(
        id="cached_job",
        file_path="uploads/test.pdf",
        status="completed",
        stage="done",
        progress=100,
    )
    db_session.add(job)
    db_session.commit()

    mock_cache.return_value = {
        "job_id": "cached_job",
        "status": "completed",
        "disclaimer": "test",
        "input_summary": {"document_type": "blood_report"},
        "abnormal_values": [],
        "normal_values": [],
        "medicines": [],
        "overall_summary": "All good",
        "questions_to_ask_doctor": [],
        "next_steps": [],
        "confidence_score": 0.9,
        "metadata": {
            "processing_time_sec": 10,
            "ocr_engine": "tesseract",
            "llm_provider": "groq",
            "model": "llama-3.3",
            "cached": True,
        },
    }

    resp = client.get("/result/cached_job")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_summary"] == "All good"


@patch("app.api.routes.result_routes.get_cached_result", return_value=None)
@patch("app.api.routes.result_routes.set_cached_result")
def test_result_from_db(mock_set_cache, mock_get_cache, client, db_session):
    job = Job(
        id="db_job",
        file_path="uploads/test.pdf",
        status="completed",
        stage="done",
        progress=100,
    )
    db_session.add(job)
    db_session.flush()

    result_row = Result(
        job_id="db_job",
        result_json={
            "job_id": "db_job",
            "status": "completed",
            "disclaimer": "test",
            "input_summary": {"document_type": "blood_report"},
            "abnormal_values": [],
            "normal_values": [],
            "medicines": [],
            "overall_summary": "DB result",
            "questions_to_ask_doctor": [],
            "next_steps": [],
            "confidence_score": 0.85,
            "metadata": {
                "processing_time_sec": 20,
                "ocr_engine": "tesseract",
                "llm_provider": "groq",
                "model": "llama-3.3",
                "cached": False,
            },
        },
        confidence=0.85,
        processing_time=20,
        llm_provider="groq",
        model="llama-3.3",
    )
    db_session.add(result_row)
    db_session.commit()

    resp = client.get("/result/db_job")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_summary"] == "DB result"
    mock_set_cache.assert_called_once()


# ---- upload ----

@patch("app.api.routes.upload.push_job", return_value=True)
@patch("app.api.routes.upload.upload_file")
@patch("app.api.routes.upload.rate_limit")
def test_upload_happy_path(mock_rate, mock_storage, mock_queue, client):
    pdf_header = b"%PDF-1.4 fake content"
    resp = client.post(
        "/upload",
        files={"file": ("report.pdf", io.BytesIO(pdf_header), "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == JOB_STATUS_QUEUED
    assert data["job_id"].startswith("job_")


@patch("app.api.routes.upload.rate_limit")
def test_upload_invalid_mime(mock_rate, client):
    resp = client.post(
        "/upload",
        files={"file": ("report.csv", io.BytesIO(b"a,b,c"), "text/csv")},
    )
    assert resp.status_code == 400
