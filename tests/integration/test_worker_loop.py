"""Integration tests for the worker run loop.

run_once is the deterministic unit (claim + process one item); a couple of
tests drive it to drain a job to completion, and one runs run_forever as a task
to confirm it drains the queue and then stops on the event.
"""

import asyncio
import logging

from sqlalchemy import select

from aiinfra.db.models import BatchJob, BatchJobItem, ItemStatus, JobStatus
from aiinfra.observability.context import CorrelationIdFilter
from aiinfra.vllm.client import VLLMCompletion
from aiinfra.worker.loop import run_forever, run_once
from tests.integration.conftest import ACTIVE_MODEL


class _OkClient:
    """Always returns a successful completion; counts calls."""

    def __init__(self):
        self.calls = 0

    async def complete(self, *, prompt, max_tokens, temperature, model=None):
        self.calls += 1
        return VLLMCompletion(
            model=model or ACTIVE_MODEL,
            output="ok",
            prompt_tokens=1,
            completion_tokens=1,
        )


async def _make_job(session, *, n_items):
    job = BatchJob(
        name="job",
        model_name=ACTIVE_MODEL,
        job_type="inference",
        status=JobStatus.QUEUED.value,
        total_items=n_items,
    )
    session.add(job)
    await session.flush()
    for i in range(n_items):
        session.add(
            BatchJobItem(
                batch_job_id=job.id,
                item_index=i,
                input_payload={"prompt": f"p{i}"},
                status=ItemStatus.QUEUED.value,
            )
        )
    await session.commit()
    return job


async def test_run_once_processes_a_single_item(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=2)

    client = _OkClient()
    assert await run_once(client, session_factory) is True

    async with session_factory() as check:
        reloaded = await check.get(BatchJob, job.id)
    assert reloaded.completed_items == 1  # exactly one, not the whole queue
    assert client.calls == 1


async def test_run_once_returns_false_on_empty_queue(session_factory):
    client = _OkClient()
    assert await run_once(client, session_factory) is False
    assert client.calls == 0


async def test_drains_job_to_completed(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=3)

    client = _OkClient()
    while await run_once(client, session_factory):
        pass

    async with session_factory() as check:
        reloaded = await check.get(BatchJob, job.id)
        items = (
            (
                await check.execute(
                    select(BatchJobItem).where(BatchJobItem.batch_job_id == job.id)
                )
            )
            .scalars()
            .all()
        )

    assert reloaded.status == JobStatus.COMPLETED.value
    assert reloaded.completed_items == 3 and reloaded.failed_items == 0
    assert reloaded.completed_at is not None
    assert all(
        it.status == ItemStatus.COMPLETED.value and it.output_payload for it in items
    )
    assert client.calls == 3


class _CaptureHandler(logging.Handler):
    """Captures records, running the correlation filter as a real handler would."""

    def __init__(self):
        super().__init__()
        self.addFilter(CorrelationIdFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_processing_logs_carry_correlation_ids(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=1)

    # Capture on the "aiinfra" logger at INFO (tests don't run configure_logging).
    handler = _CaptureHandler()
    aiinfra_logger = logging.getLogger("aiinfra")
    prev_level = aiinfra_logger.level
    aiinfra_logger.addHandler(handler)
    aiinfra_logger.setLevel(logging.INFO)
    try:
        await run_once(_OkClient(), session_factory)
    finally:
        aiinfra_logger.removeHandler(handler)
        aiinfra_logger.setLevel(prev_level)

    processed = [r for r in handler.records if r.getMessage() == "processed item"]
    assert processed, "expected a 'processed item' log line"
    assert processed[0].job_id == str(job.id)
    assert getattr(processed[0], "item_id", None)  # bound from the claimed item


async def test_run_forever_drains_then_stops_on_event(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=2)

    client = _OkClient()
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_forever(client, session_factory, stop_event=stop, poll_seconds=0.01)
    )

    # Poll (fresh session each time) until the loop finishes the job.
    completed = False
    for _ in range(300):
        async with session_factory() as check:
            reloaded = await check.get(BatchJob, job.id)
        if reloaded.status == JobStatus.COMPLETED.value:
            completed = True
            break
        await asyncio.sleep(0.01)

    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert completed
    assert reloaded.completed_items == 2
