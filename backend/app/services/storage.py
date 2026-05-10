import os
import boto3
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("storage")

_s3_client = None


def _get_s3():
    """Return the S3 client, initialised lazily so local-storage mode doesn't require AWS creds."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=settings.S3_REGION)
    return _s3_client


def upload_file(local_path: str, s3_key: str) -> str:
    _get_s3().upload_file(local_path, settings.S3_BUCKET, s3_key)
    logger.info("uploaded %s to s3://%s/%s", local_path, settings.S3_BUCKET, s3_key)
    return s3_key

def download_file(s3_key: str, local_path: str) -> str:
    _get_s3().download_file(settings.S3_BUCKET, s3_key, local_path)
    logger.info("downloaded s3://%s/%s to %s", settings.S3_BUCKET, s3_key, local_path)
    return local_path

def delete_file(s3_key: str):
    _get_s3().delete_object(Bucket=settings.S3_BUCKET, Key=s3_key)
    logger.info("deleted s3://%s/%s", settings.S3_BUCKET, s3_key)
