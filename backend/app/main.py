from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.api.routes.upload import router as upload_router
from app.api.routes.status import router as status_router
from app.api.routes.result_routes import router as result_router
from app.services.job_lifecycle import cleanup_old_jobs
from app.services.scheduler import start_scheduler
from app.models import job, result  # noqa: F401 — registers models with SQLAlchemy

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background services on startup; placeholder for shutdown cleanup."""
    logger.info("Starting background scheduler")
    start_scheduler()
    yield
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    setup_logging()
    init_db()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Lumen API - Medical Report & Prescription Explainer",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_cache_headers(request, call_next):
        response = await call_next(request)

        if request.url.path.startswith("/result/") and request.method == "GET":
            response.headers["Cache-Control"] = "public, max-age=3600"
            response.headers["Pragma"] = "cache"
        elif request.url.path.startswith("/status/") and request.method == "GET":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response

    app.include_router(upload_router, tags=["upload"])
    app.include_router(status_router, tags=["status"])
    app.include_router(result_router, tags=["result"])

    @app.get("/health")
    def health():
        return {"status": "ok", "app": settings.APP_NAME}

    @app.post("/admin/cleanup")
    def trigger_cleanup(x_admin_token: str = Header(None)):
        if settings.REQUIRE_API_KEY and (not x_admin_token or x_admin_token != settings.API_KEY):
            logger.warning("Unauthorized cleanup attempt")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing admin token"
            )

        db = SessionLocal()
        try:
            logger.info("Manual cleanup triggered via API")
            result = cleanup_old_jobs(db)
            return {
                "status": "success",
                "cleanup_result": result
            }
        except Exception as e:
            logger.error(f"Manual cleanup failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cleanup failed: {str(e)}"
            )
        finally:
            db.close()

    return app


# Module-level app instance used by uvicorn (app.main:app).
# Must be at module scope — not inside __main__ guard.
app = create_app()
