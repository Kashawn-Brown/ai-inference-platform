"""Integration tests for the worker claim layer.

Exercise the SELECT ... FOR UPDATE SKIP LOCKED claim against the test DB:
ordering, status transitions, empty-queue handling, and the no-double-claim
guarantee when a row is already locked by another transaction.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from aiinfra.db.models import BatchJob, BatchJobItem, ItemStatus, JobStatus
from aiinfra.worker.claim import claim_next_item, measure_queue_lag
from tests.integration.conftest import ACTIVE_MODEL


async def _make_job(session, *, n_items, name="job"):
    job = BatchJob(
        name=name,
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


async def test_claim_marks_item_and_job_running(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=2)

    async with session_factory() as session:
        item = await claim_next_item(session)

    assert item is not None
    assert item.status == ItemStatus.RUNNING.value

    # Confirm persisted state from a fresh session.
    async with session_factory() as check:
        reloaded_item = await check.get(BatchJobItem, item.id)
        reloaded_job = await check.get(BatchJob, job.id)
    assert reloaded_item.status == ItemStatus.RUNNING.value
    assert reloaded_job.status == JobStatus.RUNNING.value
    assert reloaded_job.started_at is not None


async def test_claim_returns_items_in_order(session_factory):
    async with session_factory() as setup:
        await _make_job(setup, n_items=3)

    async with session_factory() as session:
        first = await claim_next_item(session)
        second = await claim_next_item(session)

    assert first.item_index == 0
    assert second.item_index == 1


async def test_claim_returns_none_when_queue_empty(session_factory):
    async with session_factory() as session:
        assert await claim_next_item(session) is None


async def test_claim_stamps_started_at_once(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=2)

    async with session_factory() as session:
        await claim_next_item(session)
    async with session_factory() as check:
        first_started = (await check.get(BatchJob, job.id)).started_at

    async with session_factory() as session:
        await claim_next_item(session)
    async with session_factory() as check:
        second_started = (await check.get(BatchJob, job.id)).started_at

    assert first_started == second_started  # not re-stamped on the 2nd claim


async def _add_item(session, *, job_id, index, status, age_seconds):
    """Add one item to `job_id` with created_at backdated by `age_seconds`."""
    session.add(
        BatchJobItem(
            batch_job_id=job_id,
            item_index=index,
            input_payload={"prompt": f"p{index}"},
            status=status,
            created_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
        )
    )


async def test_queue_lag_zero_when_queue_empty(session_factory):
    async with session_factory() as session:
        assert await measure_queue_lag(session) == 0.0


async def test_queue_lag_reflects_oldest_queued_item(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=0)
        await _add_item(
            setup,
            job_id=job.id,
            index=0,
            status=ItemStatus.QUEUED.value,
            age_seconds=30,
        )
        await setup.commit()

    async with session_factory() as session:
        lag = await measure_queue_lag(session)

    assert lag >= 30.0  # at least the backdated age


async def test_queue_lag_ignores_non_queued_items(session_factory):
    # An old already-processed item must not count; only queued work is backlog.
    async with session_factory() as setup:
        job = await _make_job(setup, n_items=0)
        await _add_item(
            setup,
            job_id=job.id,
            index=0,
            status=ItemStatus.COMPLETED.value,
            age_seconds=300,
        )
        await _add_item(
            setup, job_id=job.id, index=1, status=ItemStatus.QUEUED.value, age_seconds=5
        )
        await setup.commit()

    async with session_factory() as session:
        lag = await measure_queue_lag(session)

    assert 5.0 <= lag < 300.0  # the queued item, not the old completed one


async def test_locked_row_is_skipped(session_factory):
    async with session_factory() as setup:
        await _make_job(setup, n_items=1)

    # Holder locks the only queued row in an open transaction; a second claimer
    # must skip it (SKIP LOCKED) rather than block or double-claim.
    async with session_factory() as holder, session_factory() as claimer:
        locked = (
            (
                await holder.execute(
                    select(BatchJobItem)
                    .where(BatchJobItem.status == ItemStatus.QUEUED.value)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        assert locked is not None  # holder owns the row lock now

        assert await claim_next_item(claimer) is None

        await holder.rollback()
