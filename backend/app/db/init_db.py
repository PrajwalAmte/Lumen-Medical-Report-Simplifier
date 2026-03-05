import os

from alembic import command
from alembic.config import Config

from app.core.logging import get_logger

# Import models so they register with Base.metadata (used by Alembic env.py).
from app.models.job import Job  # noqa: F401
from app.models.feedback import Feedback  # noqa: F401
from app.models.result import Result  # noqa: F401

logger = get_logger("init_db")

# Path to alembic.ini — one level above the app/ package.
_ALEMBIC_INI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "alembic.ini",
)


def init_db():
    """Apply all pending Alembic migrations (equivalent of `alembic upgrade head`).

    Called once at application startup so the schema is always up-to-date
    without requiring a manual migration step in CI / Docker entrypoints.
    """
    logger.info("Running Alembic migrations (upgrade head) …")
    alembic_cfg = Config(_ALEMBIC_INI)
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations applied successfully")
