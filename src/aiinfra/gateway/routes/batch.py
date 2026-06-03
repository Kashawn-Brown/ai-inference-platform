"""Batch job endpoints (brief Section 3).

Submit / list / get / list-items. The gateway does CRUD only: it records jobs
and their items as `queued` and resolves the job's `model_name` — it never
processes items or calls vLLM. The worker claim->process loop handles execution.

Model resolution keeps `model_configs` the source of truth: an omitted `model`
is stamped from the active config; a supplied `model` is validated to exist.

Listing uses keyset pagination — jobs by (created_at desc, id desc), items by
item_index — via opaque cursors (see aiinfra.gateway.pagination).
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from aiinfra.db.models import BatchJob, BatchJobItem, ItemStatus, JobStatus, ModelConfig
from aiinfra.db.session import get_session
from aiinfra.gateway.pagination import decode_cursor, encode_cursor
from aiinfra.schemas.batch import (
    BatchJobCreate,
    BatchJobItemList,
    BatchJobItemRead,
    BatchJobList,
    BatchJobRead,
)

logger = logging.getLogger("aiinfra.gateway.batch")
router = APIRouter(tags=["batch"])

_JOB_STATUSES = {s.value for s in JobStatus}
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


async def _resolve_model_name(session: AsyncSession, requested: str | None) -> str:
    """Resolve the job's model_name against model_configs (the source of truth).

    Omitted -> the active config's name. Supplied -> must exist (active or not).
    """
    if requested is None:
        stmt = (
            select(ModelConfig)
            .where(ModelConfig.is_active.is_(True))
            .order_by(ModelConfig.created_at.asc())
            .limit(1)
        )
        config = (await session.execute(stmt)).scalars().first()
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No active model config is available.",
            )
        return config.model_name

    stmt = select(ModelConfig).where(ModelConfig.model_name == requested).limit(1)
    config = (await session.execute(stmt)).scalars().first()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown model: {requested!r}.",
        )
    return config.model_name


@router.post(
    "/v1/batch/jobs",
    response_model=BatchJobRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_job(
    payload: BatchJobCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchJobRead:
    model_name = await _resolve_model_name(session, payload.model)

    job = BatchJob(
        name=payload.name,
        submitted_by=payload.submitted_by,
        model_name=model_name,
        job_type=payload.job_type,
        status=JobStatus.QUEUED.value,
        total_items=len(payload.items),
    )
    session.add(job)
    await session.flush()  # assign job.id before inserting items

    for index, item in enumerate(payload.items):
        session.add(
            BatchJobItem(
                batch_job_id=job.id,
                item_index=index,
                input_payload=item.input_payload,
                status=ItemStatus.QUEUED.value,
            )
        )

    await session.commit()
    await session.refresh(job)

    logger.info(
        "batch job submitted",
        extra={
            "job_id": str(job.id),
            "total_items": job.total_items,
            "model_name": job.model_name,
            "status": job.status,
        },
    )
    return BatchJobRead.model_validate(job)


@router.get("/v1/batch/jobs", response_model=BatchJobList)
async def list_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    cursor: str | None = None,
) -> BatchJobList:
    if status_filter is not None and status_filter not in _JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown status filter: {status_filter!r}.",
        )

    stmt = select(BatchJob).order_by(BatchJob.created_at.desc(), BatchJob.id.desc())
    if status_filter is not None:
        stmt = stmt.where(BatchJob.status == status_filter)
    if cursor is not None:
        created_at, job_id = _decode_job_cursor(cursor)
        stmt = stmt.where(
            tuple_(BatchJob.created_at, BatchJob.id) < (created_at, job_id)
        )

    stmt = stmt.limit(limit + 1)  # over-fetch one to detect a next page
    rows = (await session.execute(stmt)).scalars().all()

    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = encode_cursor(
            {"created_at": last.created_at.isoformat(), "id": str(last.id)}
        )
    return BatchJobList(
        jobs=[BatchJobRead.model_validate(job) for job in page],
        next_cursor=next_cursor,
    )


@router.get("/v1/batch/jobs/{job_id}", response_model=BatchJobRead)
async def get_job(
    job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchJobRead:
    job = await session.get(BatchJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )
    return BatchJobRead.model_validate(job)


@router.get("/v1/batch/jobs/{job_id}/items", response_model=BatchJobItemList)
async def list_job_items(
    job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    cursor: str | None = None,
) -> BatchJobItemList:
    if await session.get(BatchJob, job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    stmt = (
        select(BatchJobItem)
        .where(BatchJobItem.batch_job_id == job_id)
        .order_by(BatchJobItem.item_index.asc())
    )
    if cursor is not None:
        stmt = stmt.where(BatchJobItem.item_index > _decode_item_cursor(cursor))

    stmt = stmt.limit(limit + 1)
    rows = (await session.execute(stmt)).scalars().all()

    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        next_cursor = encode_cursor({"item_index": page[-1].item_index})
    return BatchJobItemList(
        items=[BatchJobItemRead.model_validate(item) for item in page],
        next_cursor=next_cursor,
    )


def _decode_job_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = decode_cursor(cursor)
        return datetime.fromisoformat(data["created_at"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor."
        ) from exc


def _decode_item_cursor(cursor: str) -> int:
    try:
        value = decode_cursor(cursor)["item_index"]
        if not isinstance(value, int):
            raise ValueError("item_index must be an int")
        return value
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor."
        ) from exc
