import logging
import json
import sys
from datetime import datetime
from app.core.config import settings


class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging():
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)  # 👈 stdout for Docker
    formatter = StructuredFormatter()
    handler.setFormatter(formatter)

    root.handlers.clear()  # avoid duplicate logs
    root.addHandler(handler)


def get_logger(name: str):
    return logging.getLogger(name)
