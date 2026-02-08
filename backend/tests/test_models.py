import pytest
from datetime import datetime, timezone
from app.models.job import Job
from app.core.constants import JOB_STATUS_QUEUED, STAGE_UPLOADING


def test_job_creation(test_session):
    job = Job(
        id="test_123",
        file_path="uploads/test.pdf",
        locale="en-IN",
        context="auto",
        status=JOB_STATUS_QUEUED,
        stage=STAGE_UPLOADING,
        progress=5
    )
    
    test_session.add(job)
    test_session.commit()
    
    saved_job = test_session.query(Job).filter(Job.id == "test_123").first()
    
    assert saved_job is not None
    assert saved_job.id == "test_123"
    assert saved_job.file_path == "uploads/test.pdf"
    assert saved_job.status == JOB_STATUS_QUEUED
    assert saved_job.progress == 5


def test_job_update(test_session, sample_job_data):
    job = Job(**sample_job_data)
    test_session.add(job)
    test_session.commit()
    
    job.status = "processing"
    job.progress = 50
    job.updated_at = datetime.now(timezone.utc)
    test_session.commit()
    
    updated_job = test_session.query(Job).filter(Job.id == job.id).first()
    
    assert updated_job.status == "processing"
    assert updated_job.progress == 50


def test_job_timestamps(test_session):
    job = Job(
        id="test_timestamp",
        file_path="uploads/test.pdf",
        status=JOB_STATUS_QUEUED,
        stage=STAGE_UPLOADING,
        progress=0
    )
    
    test_session.add(job)
    test_session.commit()
    
    assert job.created_at is not None
    assert job.updated_at is not None
    assert isinstance(job.created_at, datetime)
    assert isinstance(job.updated_at, datetime)