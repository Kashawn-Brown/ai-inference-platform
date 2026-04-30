"""Worker entrypoint.

Phase 0: idle only. Logs once at startup and sleeps in a loop. The
claim/process logic for batch items arrives in Phase 2.

Run with: python -m aiinfra.worker.main
"""

import logging
import time

from aiinfra.config import get_settings
from aiinfra.logging import configure_logging

# Logger for the worker process.
logger = logging.getLogger("aiinfra.worker")


def main() -> None:
    # Load settings and configure logging.
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    # Calculate the poll interval in seconds.
    poll_seconds = settings.worker_poll_interval_ms / 1000
    logger.info("idle, waiting for jobs")

    try:
        while True:
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
