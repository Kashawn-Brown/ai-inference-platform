"""Worker run loop — drain the queue, then poll.

`run_once` claims and processes a single item (the smallest testable unit);
`run_forever` drives it until a stop event fires, sleeping
WORKER_POLL_INTERVAL_MS when the queue is empty. Both take the session factory
and vLLM client as arguments so tests can supply a test DB and a fake client.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiinfra.observability.context import correlation_context
from aiinfra.observability.metrics import set_queue_lag
from aiinfra.vllm.client import VLLMClient
from aiinfra.worker.claim import claim_next_item, measure_queue_lag
from aiinfra.worker.processor import process_item

logger = logging.getLogger("aiinfra.worker.loop")


async def run_once(
    client: VLLMClient, factory: async_sessionmaker[AsyncSession]
) -> bool:
    """Claim and process one item. Returns False if the queue was empty."""
    async with factory() as session:
        item = await claim_next_item(session)
        if item is None:
            return False
        # Bind job/item ids so every log line processing emits carries them.
        with correlation_context(job_id=str(item.batch_job_id), item_id=str(item.id)):
            await process_item(session, client, item)
        return True


async def run_forever(
    client: VLLMClient,
    factory: async_sessionmaker[AsyncSession],
    *,
    stop_event: asyncio.Event,
    poll_seconds: float,
) -> None:
    """Process items until `stop_event` is set, polling when the queue is dry."""
    while not stop_event.is_set():
        await _sample_queue_lag(factory)
        try:
            did_work = await run_once(client, factory)
        except Exception as exc:
            # Stay alive on an unexpected per-item error (e.g. a DB blip); the
            # next iteration uses a fresh session. Logged, not swallowed.
            logger.error("worker iteration failed", extra={"error": str(exc)})
            did_work = False
        if not did_work:
            await _sleep_or_stop(stop_event, poll_seconds)


async def _sample_queue_lag(factory: async_sessionmaker[AsyncSession]) -> None:
    """Update the queue-lag gauge from a short read-only session each iteration.

    Kept out of run_once so that stays the clean claim+process test unit; one
    extra lightweight SELECT per loop is negligible against the vLLM call.
    Best-effort: a metrics-query blip is logged, never allowed to stall the
    claim/process cycle, so it runs outside the run_once error path.
    """
    try:
        async with factory() as session:
            set_queue_lag(await measure_queue_lag(session))
    except Exception as exc:
        logger.warning("queue lag sample failed", extra={"error": str(exc)})


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    """Sleep up to `seconds`, returning early if the stop event fires."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        pass
