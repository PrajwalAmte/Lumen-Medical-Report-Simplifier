import time
import json
import traceback
import tempfile
import os
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.job import Job
from app.core.constants import *
from app.services.ocr import extract_text
from app.services.parser import parse_medical_text
from app.services.llm import generate_explanation
from app.services.result_sanitizer import sanitize_result
from app.core.config import settings
from app.services.queue import pop_job, get_redis_client
from app.services.cache import set_cached_result
from app.services.storage import download_file
from app.core.logging import get_logger
from app.core.logging import setup_logging


def update_job(db: Session, job: Job, status: str, stage: str, progress: int, error_message: str = None):
    """Update job status and progress with database commit and error handling."""
    job.status = status
    job.stage = stage
    job.progress = progress
    job.updated_at = datetime.now(timezone.utc)
    if error_message:
        job.error_message = error_message
    try:
        db.commit()
        db.refresh(job)
        get_logger("processor").info(f"Job {job.id} status updated: {status}, progress: {progress}%")
    except Exception as e:
        get_logger("processor").error(f"Failed to update job {job.id}: {e}")
        db.rollback()


def process_job(job_id: str):
    """Main job processing pipeline: OCR -> Parse -> LLM -> Store.
    
    Processes a single job through the complete pipeline:
    1. Download file from storage
    2. Extract text via OCR
    3. Parse medical entities
    4. Generate explanation via LLM
    5. Sanitize and store results
    """
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()

    # Skip if job not found or not in queued state
    if not job or job.status != JOB_STATUS_QUEUED:
        db.close()
        return

    start_time = time.time()

    try:
        # Stage 1: Text extraction via OCR
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_EXTRACTING_TEXT,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_EXTRACTING_TEXT])

        # Download file to temporary location with original extension
        original_ext = os.path.splitext(job.file_path)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_ext) as tmp:
            local_path = tmp.name

        download_file(job.file_path, local_path)
        raw_text = extract_text(local_path)
        os.remove(local_path)  # Cleanup temporary file

        if not raw_text.strip():
            raise RuntimeError("OCR returned empty text")

        # Stage 2: Parse medical entities from text
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_PARSING,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_PARSING])

        parsed_data = parse_medical_text(raw_text)

        # Stage 3: Generate explanation via LLM
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_GENERATING_EXPLANATION,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_GENERATING_EXPLANATION])

        explanation = generate_explanation(parsed_data)

        # Stage 4: Finalize and store results
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_FINALIZING,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_FINALIZING])

        processing_time = int(time.time() - start_time)

        result_payload = {
            "job_id": job.id,
            "status": JOB_STATUS_COMPLETED,
            **explanation,
            "metadata": {
                "processing_time_sec": processing_time,
                "ocr_engine": settings.OCR_ENGINE,
                "llm_provider": settings.LLM_PROVIDER,
                "model": settings.LLM_MODEL,
                "cached": False
            }
        }

        try:
            safe_result = sanitize_result(result_payload)
        except Exception:
            safe_result = sanitize_result({})


        set_cached_result(job.id, safe_result, ttl_sec=3600)

        db.execute(
            text("""
                INSERT INTO results (
                    job_id, result_json, confidence,
                    processing_time, llm_provider, model, cached, created_at
                ) VALUES (
                    :job_id, :result_json, :confidence,
                    :processing_time, :llm_provider, :model, :cached, CURRENT_TIMESTAMP
                )
            """),
            {
                "job_id": job.id,
                "result_json": json.dumps(safe_result),
                "confidence": safe_result.get("confidence_score", 0.0),
                "processing_time": processing_time,
                "llm_provider": settings.LLM_PROVIDER,
                "model": settings.LLM_MODEL,
                "cached": False
            }
        )

        update_job(db, job, JOB_STATUS_COMPLETED, STAGE_DONE,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_DONE])

    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            update_job(
                db, job, JOB_STATUS_FAILED, STAGE_FAILED,
                DEFAULT_PROGRESS_BY_STAGE[STAGE_FAILED],
                error_message=f"{type(e).__name__}: {str(e)}"
            )

        logger = get_logger("processor")
        logger.error(f"Job {job_id} failed: {e}")
        logger.error(traceback.format_exc())

    finally:
        db.close()

def run_worker():
    logger = get_logger("processor")
    redis_client = get_redis_client()

    logger.info("Worker started, waiting for jobs")

    while True:
        try:
            job_id = pop_job() 

            if job_id:
                logger.info(f"Picked job {job_id}")
                process_job(job_id)

        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            logger.error(traceback.format_exc())
            time.sleep(5)


if __name__ == "__main__":
    setup_logging() 
    run_worker()

