import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db
from app.models.job import Job
from app.models.schemas import ResultResponse
from app.services.cache import get_cached_result
from app.services.result_sanitizer import sanitize_result
from app.core.constants import JOB_STATUS_EXPIRED
from app.core.logging import get_logger

logger = get_logger("result")
router = APIRouter()


@router.get("/result/{job_id}", response_model=ResultResponse)
def get_result(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        logger.warning(f"Result requested for non-existent job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    if job.status == JOB_STATUS_EXPIRED:
        logger.warning(f"Result requested for expired job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This job has expired and is no longer available"
        )

    if job.status == "failed":
        logger.warning(f"Result requested for failed job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job processing failed: {job.error_message or 'Unknown error'}"
        )

    if job.status != "completed":
        logger.debug(f"Result requested for incomplete job {job_id}: {job.status}")
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail=f"Job not completed yet (current status: {job.status})"
        )

    try:
        cached = get_cached_result(job_id)
        if cached and isinstance(cached, dict):
            logger.debug(f"Returning cached result for job {job_id}")
            try:
                validated = ResultResponse.model_validate(cached)
                return validated
            except Exception:
                # best-effort: sanitize and validate one more time
                try:
                    sanitized_cached = sanitize_result(cached)
                    return ResultResponse.model_validate(sanitized_cached)
                except Exception:
                    return ResultResponse.model_validate({
                        "job_id": job_id,
                        "status": "completed",
                        "disclaimer": "",
                        "input_summary": {"document_type": "unknown"},
                        "abnormal_values": [],
                        "normal_values": [],
                        "medicines": [],
                        "overall_summary": "Result temporarily unavailable",
                        "questions_to_ask_doctor": [],
                        "next_steps": [],
                        "confidence_score": 0.0,
                        "metadata": {"processing_time_sec": 0, "ocr_engine": "unknown", "llm_provider": "unknown", "model": "unknown", "cached": True}
                    })
                
    except Exception as e:
        logger.warning(f"Cache read failed for {job_id}: {e}")

    result_row = db.execute(
        text("SELECT result_json FROM results WHERE job_id = :job_id"),
        {"job_id": job_id}
    ).fetchone()

    if not result_row or not result_row[0]:
        logger.error(f"Result not found in database for completed job {job_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Result not found for completed job"
        )

    try:
        result_payload = json.loads(result_row[0])
    except Exception as e:
        logger.error(f"Stored result is corrupted for job {job_id}: {e}")
        # Return a safe minimal response instead of 500
        safe = {
            "job_id": job_id,
            "status": "completed",
            "disclaimer": "",
            "input_summary": {"document_type": "unknown", "detected_language": None, "detected_hospital": None, "date_of_report": None},
            "abnormal_values": [],
            "normal_values": [],
            "medicines": [],
            "overall_summary": "Result corrupted",
            "questions_to_ask_doctor": [],
            "next_steps": [],
            "confidence_score": 0.0,
            "metadata": {"processing_time_sec": 0, "ocr_engine": "unknown", "llm_provider": "unknown", "model": "unknown", "cached": False}
        }
        return ResultResponse.model_validate(safe)

    logger.info(f"Result retrieved successfully for job {job_id}")

    # Sanitize the loaded payload to ensure no null required fields
    try:
        sanitized = sanitize_result(result_payload)
    except Exception as e:
        logger.error(f"Sanitizer failed for job {job_id}: {e}")
        sanitized = result_payload

    try:
        validated = ResultResponse.model_validate(sanitized)
        return validated
    except Exception as e:
        logger.error(f"Result schema validation failed for job {job_id}: {e}")
        # Attempt one more auto-fix pass and return a minimal safe response if still invalid
        try:
            sanitized2 = sanitize_result(sanitized)
            return ResultResponse.model_validate(sanitized2)
        except Exception as e2:
            logger.error(f"Final validation failed for job {job_id}: {e2}")
            safe = {
                "job_id": job_id,
                "status": "completed",
                "disclaimer": sanitized.get("disclaimer", ""),
                "input_summary": {"document_type": "unknown", "detected_language": None, "detected_hospital": None, "date_of_report": None},
                "abnormal_values": [],
                "normal_values": [],
                "medicines": [],
                "overall_summary": sanitized.get("overall_summary", "No data available"),
                "questions_to_ask_doctor": [],
                "next_steps": [],
                "confidence_score": float(sanitized.get("confidence_score", 0.0)),
                "metadata": sanitized.get("metadata", {"processing_time_sec": 0, "ocr_engine": "unknown", "llm_provider": "unknown", "model": "unknown", "cached": False})
            }
            return ResultResponse.model_validate(safe)