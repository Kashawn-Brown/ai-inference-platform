"""Structured logging setup.

stdlib logging configured to emit one JSON object per log record on stdout.
Used by both gateway and worker entrypoints. Correlation IDs and per-request
fields arrive in Phase 1 / Phase 3.
"""

import json
import logging
import sys
from datetime import UTC, datetime


# Custom JSON formatter for the logging system.
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# Configure logging for the application.
def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    # Replace any prior handlers (e.g. uvicorn's defaults) so output stays
    # consistent across the process.
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
