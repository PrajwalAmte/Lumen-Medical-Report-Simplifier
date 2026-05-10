from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Optional
import os

# Base directory (used by relative path settings)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    """Application settings — all values overridable via environment variables."""

    APP_NAME: str = "Lumen"
    ENV: str = "development"
    IS_PROD: bool = False

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:////data/lumen.db"
    )

    REDIS_URL: str = "redis://redis:6379/0"
    QUEUE_NAME: str = "lumen_jobs"
    REDIS_RESULT_TTL_SECONDS: int = 86400

    STORAGE_TYPE: str = "s3"
    STORAGE_PATH: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    S3_REGION: str = "ap-south-1"
    S3_TTL_DAYS: int = 7

    MAX_FILE_SIZE_MB: int = 10
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".jpg", ".jpeg", ".png"]

    CORS_ORIGINS: List[str] = ["*"]
    RATE_LIMIT_PER_MINUTE: int = 10

    # ------------------------------------------------------------------
    #  LLM configuration
    # ------------------------------------------------------------------
    LLM_PROVIDER: str = "groq"          # groq | openai | llama | ollama

    GROQ_API_KEY: Optional[str] = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    OPENAI_API_KEY: Optional[str] = None

    LLAMA_ENDPOINT: str = "http://localhost:11434"
    LLAMA_MODEL: str = "llama3.1:8b"
    LLAMA_MAX_TOKENS: int = 4096

    # Model routing: heavy model for full analysis, light model for
    # simpler tasks (medicine lookups, summary generation, etc.)
    LLM_MODEL_HEAVY: str = "llama-3.3-70b-versatile"
    LLM_MODEL_LIGHT: str = "openai/gpt-oss-20b"

    # Token limits — Llama 3.3 70B max output = 32 768
    LLM_MAX_TOKENS_HEAVY: int = 4096
    LLM_MAX_TOKENS_LIGHT: int = 2048

    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT_SEC: int = 90
    LLM_RETRY_COUNT: int = 3
    LLM_RETRY_BACKOFF_SEC: int = 2

    # ------------------------------------------------------------------
    #  RAG / Embeddings (pgvector + Jina AI)
    # ------------------------------------------------------------------
    RAG_ENABLED: bool = True
    JINA_API_KEY: Optional[str] = None
    JINA_EMBEDDING_MODEL: str = "jina-embeddings-v3"
    JINA_DIMENSIONS: int = 512
    RAG_TOP_K: int = 5

    OCR_ENGINE: str = "tesseract"

    # ------------------------------------------------------------------
    #  Vision LLM tier (Phase 4) — complex/degraded/multi-modal pages
    # ------------------------------------------------------------------
    VISION_ENABLED: bool = True
    # "openai" uses GPT-4o; "local" uses Ollama (PHI-compliant, on-premise)
    VISION_PROVIDER: str = "openai"
    VISION_MODEL: str = "gpt-4o"
    VISION_TIMEOUT_SEC: int = 60
    # Resize the long side of the image to this before sending to the API
    # (reduces token cost; 1024 gives adequate resolution for text)
    VISION_MAX_SIDE_PX: int = 1024
    LOCAL_VISION_ENDPOINT: str = "http://localhost:11434"
    LOCAL_VISION_MODEL: str = "llava:13b"

    LOG_LEVEL: str = "INFO"

    REQUIRE_API_KEY: bool = True
    API_KEY: str = ""
    # Separate admin token — must differ from API_KEY in production
    ADMIN_TOKEN: str = ""

    JOB_EXPIRY_DAYS: int = 7
    JOB_HARD_DELETE_DAYS: int = 30
    CLEANUP_INTERVAL_HOURS: int = 24

    # Watchdog: maximum minutes a job can stay in "processing" before
    # it is considered stuck (worker crash recovery).
    STUCK_JOB_TIMEOUT_MINUTES: int = 10
    # How often (in seconds) the worker polls for orphaned "queued" jobs
    # that were never pushed to Redis (issue #18 safety net).
    QUEUED_POLL_INTERVAL_SEC: int = 30
    # Number of worker threads that run pipeline jobs concurrently.
    WORKER_CONCURRENCY: int = 4

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v

    @field_validator("GROQ_API_KEY")
    @classmethod
    def validate_groq_key(cls, v):
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

if settings.ENV == "production" and settings.LLM_PROVIDER == "groq" and not settings.GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY must be set in production when LLM_PROVIDER=groq")

if settings.STORAGE_TYPE == "s3" and not settings.S3_BUCKET:
    raise RuntimeError("S3_BUCKET must be set when STORAGE_TYPE=s3")
