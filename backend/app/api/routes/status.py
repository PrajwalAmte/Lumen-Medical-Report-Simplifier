from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.job import Job
from app.models.schemas import StatusResponse
from app.core.security import api_key_auth
from app.core.constants import JOB_STATUS_EXPIRED
from app.core.logging import get_logger

logger = get_logger("status")
router = APIRouter()


@router.get(
    "/status/{job_id}",
    response_model=StatusResponse,
    dependencies=[Depends(api_key_auth)]
)
def get_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        logger.warning(f"Status requested for non-existent job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    if job.status == JOB_STATUS_EXPIRED:
        logger.warning(f"Status requested for expired job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This job has expired and is no longer available"
        )

    logger.debug(f"Status retrieved for job {job_id}: {job.status}")

    return StatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        updated_at=job.updated_at,
    )
