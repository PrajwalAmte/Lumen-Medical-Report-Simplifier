import os
import boto3
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("storage")

s3 = boto3.client("s3", region_name=settings.S3_REGION)

def upload_file(local_path: str, s3_key: str) -> str:
    s3.upload_file(local_path, settings.S3_BUCKET, s3_key)
    logger.info("uploaded %s to s3://%s/%s", local_path, settings.S3_BUCKET, s3_key)
    return s3_key

def download_file(s3_key: str, local_path: str) -> str:
    s3.download_file(settings.S3_BUCKET, s3_key, local_path)
    logger.info("downloaded s3://%s/%s to %s", settings.S3_BUCKET, s3_key, local_path)
    return local_path

def delete_file(s3_key: str):
    s3.delete_object(Bucket=settings.S3_BUCKET, Key=s3_key)
    logger.info("deleted s3://%s/%s", settings.S3_BUCKET, s3_key)
