"""Structured logging setup.

stdlib logging configured to emit one JSON object per log record on stdout.
Used by both gateway and worker entrypoints. A CorrelationIdFilter on the
handler stamps the current request_id/job_id/item_id onto every record, so
correlation fields appear without each call site passing them by hand.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from aiinfra.observability.context import CorrelationIdFilter

# LogRecord attributes that are part of the record itself, not caller-supplied
# context. Anything outside this set arrived via `extra=` and gets merged into
# the JSON payload (request_id, status, latency_ms, ...). Computed from a blank
# record so it stays correct across Python versions.
_RESERVED_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


# Custom JSON formatter for the logging system.
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge caller-supplied `extra` fields (per-request context).
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS:
                payload[key] = value
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
    # Inject correlation fields (request_id/job_id/item_id) onto every record.
    handler.addFilter(CorrelationIdFilter())

    # Replace any prior handlers (e.g. uvicorn's defaults) so output stays
    # consistent across the process.
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
