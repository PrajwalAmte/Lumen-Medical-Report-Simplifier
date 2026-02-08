import os
from fastapi import UploadFile, HTTPException, status, Request, Header
from app.core.config import settings

# File magic bytes for content validation (prevents file type spoofing)
MAGIC_BYTES = {
    'pdf': b'%PDF',  # PDF files start with "%PDF"
    'jpeg': [b'\xFF\xD8\xFF'],  # JPEG files start with these bytes
    'png': b'\x89PNG',  # PNG files start with PNG signature
}

def validate_file(file: UploadFile):
    """Validate file extension against allowed types.
    
    Args:
        file: Uploaded file object
        
    Raises:
        HTTPException: 400 if file extension not allowed
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )


def validate_file_magic_bytes(file_content: bytes, filename: str):
    """Validate file content matches declared file type (prevents spoofing).
    
    This is a security measure to ensure uploaded files are actually
    the type they claim to be based on their extension.
    
    Args:
        file_content: Raw file bytes
        filename: Original filename with extension
        
    Raises:
        HTTPException: 400 if file content doesn't match extension
    """
    ext = os.path.splitext(filename)[1].lower().lstrip('.')

    if ext == 'pdf':
        if not file_content.startswith(MAGIC_BYTES['pdf']):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid PDF file. File content does not match PDF format.'
            )
    elif ext in ['jpg', 'jpeg']:
        # JPEG can have multiple valid magic byte signatures
        is_valid_jpeg = False
        for magic_prefix in MAGIC_BYTES['jpeg']:
            if file_content.startswith(magic_prefix):
                is_valid_jpeg = True
                break

        if not is_valid_jpeg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid JPEG file. File content does not match JPEG format.'
            )
    elif ext == 'png':
        if not file_content.startswith(MAGIC_BYTES['png']):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid PNG file. File content does not match PNG format.'
            )


def validate_file_size(file_content: bytes):
    """Validate file size is within allowed limits.
    
    Args:
        file_content: Raw file bytes
        
    Raises:
        HTTPException: 413 if file exceeds size limit
    """
    size_mb = len(file_content) / (1024 * 1024)

    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE_MB} MB. Your file: {size_mb:.2f} MB"
        )


def api_key_auth(x_api_key: str = Header(None)):
    """API key authentication dependency.
    
    Args:
        x_api_key: API key from X-API-Key header
        
    Raises:
        HTTPException: 401 if API key is required but invalid/missing
    """
    if settings.REQUIRE_API_KEY:
        if not x_api_key or x_api_key != settings.API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key"
            )
