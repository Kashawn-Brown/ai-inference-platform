"""Worker entrypoint.

Builds the shared vLLM client and async session factory, installs signal
handlers for graceful shutdown, and runs the claim -> process loop until
stopped. The worker calls vLLM directly (never through the gateway).

Run with: python -m aiinfra.worker.main
"""

import asyncio
import logging
import signal

from aiinfra.config import Settings, get_settings
from aiinfra.db.engine import get_engine
from aiinfra.db.session import get_session_factory
from aiinfra.logging import configure_logging
from aiinfra.vllm.client import VLLMClient
from aiinfra.worker.loop import run_forever

logger = logging.getLogger("aiinfra.worker")


async def _run(settings: Settings) -> None:
    client = VLLMClient.from_settings(settings)
    factory = get_session_factory()
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    logger.info("worker started")
    try:
        await run_forever(
            client,
            factory,
            stop_event=stop_event,
            poll_seconds=settings.worker_poll_interval_ms / 1000,
        )
    finally:
        await client.aclose()
        await get_engine().dispose()
        logger.info("worker stopped")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows loops don't support add_signal_handler; a Ctrl+C there
            # raises KeyboardInterrupt, which main() turns into clean shutdown.
            pass


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
