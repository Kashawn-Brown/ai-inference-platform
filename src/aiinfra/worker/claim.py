"""Worker claim — atomically take the next queued batch item.

The queue read at the heart of the worker: SELECT ... FOR UPDATE SKIP LOCKED
over queued items (the brief's no-Redis queue mechanism). Claiming transitions
the item to running and its job to running (stamping started_at once), in a
single short transaction so the row lock is released before the slow vLLM call
in the processing step — a long-held lock would block other workers.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiinfra.db.models import BatchJob, BatchJobItem, ItemStatus, JobStatus

logger = logging.getLogger("aiinfra.worker.claim")


async def claim_next_item(session: AsyncSession) -> BatchJobItem | None:
    """Claim the oldest queued item, marking it (and its job) running.

    Returns the claimed item, or None if no queued item is available. Commits
    before returning so the row lock is released and the item won't be
    re-claimed. The session must use expire_on_commit=False so the returned
    item stays usable after the commit.
    """
    stmt = (
        select(BatchJobItem)
        .where(BatchJobItem.status == ItemStatus.QUEUED.value)
        .order_by(BatchJobItem.created_at, BatchJobItem.item_index)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    item = (await session.execute(stmt)).scalars().first()
    if item is None:
        return None

    item.status = ItemStatus.RUNNING.value

    # Move the parent job to running on its first claimed item. Single-worker
    # v1, so the job-row race here is benign; guards keep it idempotent.
    job = await session.get(BatchJob, item.batch_job_id)
    if job is not None:
        if job.status == JobStatus.QUEUED.value:
            job.status = JobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)

    await session.commit()
    logger.info(
        "claimed item",
        extra={"item_id": str(item.id), "job_id": str(item.batch_job_id)},
    )
    return item
