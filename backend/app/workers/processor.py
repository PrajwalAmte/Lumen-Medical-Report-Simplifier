"""
Async worker: Download → OCR → Parse → (RAG) → LLM → Store.

On startup a watchdog re-queues jobs stuck in "processing" (crash recovery).
A DB-poll loop runs every QUEUED_POLL_INTERVAL_SEC as a Redis fallback.
Up to WORKER_CONCURRENCY jobs run concurrently via asyncio.Semaphore.
"""

import asyncio
import time
import traceback
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.job import Job
from app.models.result import Result
from app.core.constants import (
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    STAGE_UPLOADING,
    STAGE_EXTRACTING_TEXT,
    STAGE_PARSING,
    STAGE_GENERATING_EXPLANATION,
    STAGE_FINALIZING,
    STAGE_DONE,
    STAGE_FAILED,
    DEFAULT_PROGRESS_BY_STAGE,
)
from app.services.ocr import extract_text
from app.services.parser import parse_medical_text
from app.services.llm import generate_explanation_async
from app.services.retrieval import retrieve_context
from app.services.result_sanitizer import sanitize_result
from app.core.config import settings
from app.services.queue import pop_job, push_job
from app.services.redis_client import get_redis_client
from app.services.cache import set_cached_result
from app.services.storage import download_file
from app.core.logging import get_logger, setup_logging

logger = get_logger("processor")

_executor = ThreadPoolExecutor(max_workers=settings.WORKER_CONCURRENCY)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

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
        logger.info(f"Job {job.id} status updated: {status}, progress: {progress}%")
    except Exception as e:
        logger.error(f"Failed to update job {job.id}: {e}")
        db.rollback()


# ---------------------------------------------------------------------------
#  #16 – Dead-job recovery watchdog
# ---------------------------------------------------------------------------

def recover_stuck_jobs() -> int:
    """Fail or re-queue jobs stuck in 'processing' longer than the timeout.

    Called once on worker startup so that a previous crash doesn't leave
    jobs in limbo forever.  Returns the number of recovered jobs.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_JOB_TIMEOUT_MINUTES)
        stuck = (
            db.query(Job)
            .filter(Job.status == JOB_STATUS_PROCESSING, Job.updated_at < cutoff)
            .all()
        )
        for job in stuck:
            logger.warning(f"Recovering stuck job {job.id} (last updated {job.updated_at})")
            # Re-queue so the job gets a second chance.
            job.status = JOB_STATUS_QUEUED
            job.stage = STAGE_UPLOADING
            job.progress = 0
            job.error_message = None
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            if not push_job(job.id):
                logger.error(f"Re-queue failed for stuck job {job.id}, marking as failed")
                update_job(db, job, JOB_STATUS_FAILED, STAGE_FAILED,
                           DEFAULT_PROGRESS_BY_STAGE[STAGE_FAILED],
                           error_message="Worker crash recovery failed — could not re-queue")
        logger.info(f"Watchdog recovered {len(stuck)} stuck job(s)")
        return len(stuck)
    except Exception as e:
        logger.error(f"Watchdog error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
#  #18 – DB-poll fallback for orphaned "queued" jobs
# ---------------------------------------------------------------------------

def poll_orphaned_queued_jobs() -> list[str]:
    """Return job IDs that are 'queued' in the DB but likely not in Redis.

    A job is considered orphaned if it has been in 'queued' status for
    longer than 60 seconds (generous grace period for normal push latency).
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        orphans = (
            db.query(Job.id)
            .filter(Job.status == JOB_STATUS_QUEUED, Job.updated_at < cutoff)
            .all()
        )
        ids = [row[0] for row in orphans]
        if ids:
            logger.info(f"DB-poll found {len(ids)} orphaned queued job(s): {ids}")
        return ids
    except Exception as e:
        logger.error(f"DB-poll error: {e}")
        return []
    finally:
        db.close()


# ---------------------------------------------------------------------------
#  #20 – Async job pipeline
# ---------------------------------------------------------------------------

async def process_job(job_id: str):
    """Async job processing pipeline: Download → OCR → Parse → LLM → Store.

    CPU-bound steps (OCR, parsing) are offloaded to a thread-pool.
    The LLM call uses the async Groq client.
    """
    loop = asyncio.get_running_loop()
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job or job.status != JOB_STATUS_QUEUED:
        db.close()
        return

    start_time = time.time()

    try:
        # Stage 1: Text extraction via OCR (CPU-bound → thread-pool)
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_EXTRACTING_TEXT,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_EXTRACTING_TEXT])

        original_ext = os.path.splitext(job.file_path)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_ext) as tmp:
            local_path = tmp.name

        try:
            await loop.run_in_executor(_executor, download_file, job.file_path, local_path)
            raw_text = await loop.run_in_executor(_executor, extract_text, local_path)
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

        if not raw_text.strip():
            raise RuntimeError("OCR returned empty text")

        # Stage 2: Parse medical entities (CPU-bound → thread-pool)
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_PARSING,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_PARSING])

        parsed_data = await loop.run_in_executor(_executor, parse_medical_text, raw_text)

        parsed_data["raw_text"] = raw_text
        logger.info(
            f"Job {job_id} parsed: {len(parsed_data.get('tests', []))} tests, "
            f"{len(parsed_data.get('medicines', []))} medicines, "
            f"{len(raw_text)} OCR chars"
        )

        # Stage 3: Generate explanation via async LLM call
        update_job(db, job, JOB_STATUS_PROCESSING, STAGE_GENERATING_EXPLANATION,
                   DEFAULT_PROGRESS_BY_STAGE[STAGE_GENERATING_EXPLANATION])

        # RAG: retrieve relevant knowledge chunks (skipped when RAG_ENABLED=false)
        retrieval_context = await loop.run_in_executor(
            _executor, retrieve_context, parsed_data
        )
        if retrieval_context:
            logger.info(
                f"Job {job_id}: RAG retrieved {len(retrieval_context)} chunks"
            )

        explanation = await generate_explanation_async(
            parsed_data, retrieval_context=retrieval_context
        )

        # Pop internal key so it doesn't reach the frontend
        model_used = explanation.pop("_llm_model_used", settings.LLM_MODEL_HEAVY)

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
                "model": model_used,
                "cached": False
            }
        }

        try:
            safe_result = sanitize_result(result_payload)
        except Exception:
            safe_result = sanitize_result({})

        set_cached_result(job.id, safe_result, ttl_sec=3600)

        result_row = Result(
            job_id=job.id,
            result_json=safe_result,
            confidence=safe_result.get("confidence_score", 0.0),
            processing_time=processing_time,
            llm_provider=settings.LLM_PROVIDER,
            model=model_used,
            cached=False,
        )
        db.add(result_row)

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
        logger.error(f"Job {job_id} failed: {e}")
        logger.error(traceback.format_exc())

    finally:
        db.close()


# ---------------------------------------------------------------------------
#  Worker loop — Redis queue + DB-poll, bounded concurrency via Semaphore
# ---------------------------------------------------------------------------

async def _redis_consumer(sem: asyncio.Semaphore):
    """Primary job source: Redis BRPOP (blocking pop)."""
    while True:
        try:
            loop = asyncio.get_running_loop()
            job_id = await loop.run_in_executor(None, pop_job)
            if job_id:
                await sem.acquire()
                asyncio.create_task(_guarded_process(sem, job_id))
        except Exception as e:
            logger.error(f"Redis consumer error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(5)


async def _db_poller(sem: asyncio.Semaphore):
    """Fallback: periodically scan DB for queued jobs missed by Redis (#18)."""
    while True:
        try:
            await asyncio.sleep(settings.QUEUED_POLL_INTERVAL_SEC)
            loop = asyncio.get_running_loop()
            orphan_ids = await loop.run_in_executor(None, poll_orphaned_queued_jobs)
            for jid in orphan_ids:
                await sem.acquire()
                asyncio.create_task(_guarded_process(sem, jid))
        except Exception as e:
            logger.error(f"DB poller error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(10)


async def _guarded_process(sem: asyncio.Semaphore, job_id: str):
    """Run process_job and release the semaphore when done."""
    try:
        logger.info(f"Processing job {job_id}")
        await process_job(job_id)
    finally:
        sem.release()


async def run_worker_async():
    """Async entry-point: watchdog → concurrent Redis + DB-poll loops."""
    logger.info("Worker starting — running dead-job watchdog …")
    recover_stuck_jobs()

    sem = asyncio.Semaphore(settings.WORKER_CONCURRENCY)

    logger.info(
        f"Worker ready (concurrency={settings.WORKER_CONCURRENCY}, "
        f"db_poll_interval={settings.QUEUED_POLL_INTERVAL_SEC}s)"
    )

    await asyncio.gather(
        _redis_consumer(sem),
        _db_poller(sem),
    )


def run_worker():
    """Synchronous wrapper kept for backward-compat with the Dockerfile CMD."""
    asyncio.run(run_worker_async())


if __name__ == "__main__":
    setup_logging()
    run_worker()

