import os
import uuid
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import validate_file, validate_file_size, validate_file_magic_bytes, api_key_auth
from app.services.rate_limiter import rate_limit
from app.core.config import settings
from app.models.job import Job
from app.models.schemas import UploadResponse
from app.core.constants import JOB_STATUS_QUEUED, STAGE_UPLOADING
from app.services.queue import push_job
from app.services.storage import upload_file
from app.core.logging import get_logger

logger = get_logger("upload")
router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadResponse,
    dependencies=[Depends(api_key_auth)]
)
async def upload_file_route(
    request: Request,
    file: UploadFile = File(...),
    locale: str = "en-IN",
    context: str = "auto",
    db: Session = Depends(get_db),
):
    rate_limit(request)

    validate_file(file)

    allowed_mime = {"application/pdf", "image/jpeg", "image/png"}
    if file.content_type not in allowed_mime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MIME type: {file.content_type}"
        )

    file_content = await file.read()
    validate_file_size(file_content)
    validate_file_magic_bytes(file_content, file.filename)

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    file_ext = os.path.splitext(file.filename)[1].lower()
    s3_key = f"uploads/{job_id}{file_ext}"

    # Write to temp file for upload
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        upload_file(tmp_path, s3_key)
        os.remove(tmp_path)
    except Exception as e:
        logger.error(f"Failed to upload file for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")

    job = Job(
        id=job_id,
        file_path=s3_key,   # store S3 key instead of disk path
        locale=locale,
        context=context,
        status=JOB_STATUS_QUEUED,
        stage=STAGE_UPLOADING,
        progress=5,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    queued = push_job(job_id)
    if not queued:
        logger.warning(f"Failed to queue job {job_id}, will rely on DB polling")

    logger.info(f"Job {job_id} created and queued successfully")

    return UploadResponse(
        job_id=job_id,
        status=job.status,
        message="File uploaded successfully. Processing has started.",
        estimated_time_sec=40,
    )
