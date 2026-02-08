from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List
import os

# Base directory for the application
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables."""

    # Application metadata
    APP_NAME: str = "Lumen"
    ENV: str = "development"
    IS_PROD: bool = False

    # Database configuration - defaults to SQLite for development
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:////data/lumen.db"
    )

    # Redis configuration for job queue and caching
    REDIS_URL: str = "redis://redis:6379/0"
    QUEUE_NAME: str = "lumen_jobs"
    REDIS_RESULT_TTL_SECONDS: int = 86400  # 24 hours

    # File storage configuration
    STORAGE_TYPE: str = "s3"  # Options: s3, local
    STORAGE_PATH: str | None = None
    S3_BUCKET: str | None = None
    S3_REGION: str = "ap-south-1"
    S3_TTL_DAYS: int = 7  # Auto-cleanup after 7 days

    # File upload constraints
    MAX_FILE_SIZE_MB: int = 10
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".jpg", ".jpeg", ".png"]

    # CORS configuration for frontend access
    CORS_ORIGINS: List[str] = ["*"]

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 10

    # LLM configuration for medical explanations
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4.1-mini"
    LLM_MAX_TOKENS: int = 1200
    LLM_TEMPERATURE: float = 0.1

    LLM_TIMEOUT_SEC: int = 60
    LLM_RETRY_COUNT: int = 3
    LLM_RETRY_BACKOFF_SEC: int = 2
    LLM_FAIL_FAST: bool = False

    OCR_ENGINE: str = "tesseract"

    LOG_LEVEL: str = "INFO"

    REQUIRE_API_KEY: bool = True
    API_KEY: str = ""

    JOB_EXPIRY_DAYS: int = 7
    JOB_HARD_DELETE_DAYS: int = 30
    CLEANUP_INTERVAL_HOURS: int = 24

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v

    @field_validator("OPENAI_API_KEY")
    @classmethod
    def validate_openai_key(cls, v):
        if v in ("", None):
            return None
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()

if settings.ENV == "production" and not settings.OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY must be set when ENV=production")

if settings.STORAGE_TYPE == "s3" and not settings.S3_BUCKET:
    raise RuntimeError("S3_BUCKET must be set when STORAGE_TYPE=s3")
