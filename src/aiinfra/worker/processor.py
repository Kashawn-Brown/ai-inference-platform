"""Worker processing — run one claimed item through vLLM and record the result.

Given an already-claimed (running) item, resolve the job's model and serving
params from model_configs (the source of truth — never env), call vLLM
directly with one retry on a transient error, then persist the item's outcome
and bump the job's progress counters / terminal status.

The vLLM call is made with no DB transaction held: the read of job+config is
committed first (the session keeps the rows loaded via expire_on_commit=False),
so a slow model call doesn't sit idle inside an open transaction.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiinfra.db.models import BatchJob, BatchJobItem, ItemStatus, JobStatus, ModelConfig
from aiinfra.observability.metrics import observe_batch_item, observe_batch_job
from aiinfra.vllm.client import (
    VLLMClient,
    VLLMConnectionError,
    VLLMError,
    VLLMTimeoutError,
)

logger = logging.getLogger("aiinfra.worker.processor")

# Fallbacks when neither the item payload nor the model config specifies them.
_DEFAULT_MAX_TOKENS = 512
_DEFAULT_TEMPERATURE = 0.7

# Transient failures get one retry; everything else fails the item immediately
# (brief §5 — revisit based on observed failure modes).
_TRANSIENT_ERRORS = (VLLMTimeoutError, VLLMConnectionError)


async def process_item(
    session: AsyncSession, client: VLLMClient, item: BatchJobItem
) -> None:
    """Process one claimed item: call vLLM, record output or error, update job.

    Always commits a terminal item state (completed/failed) and the job's
    progress; never re-raises vLLM errors (a failed item is normal flow).
    """
    # End-to-end processing time (config read + the dominant vLLM call); the
    # histogram's per-status _count is also the items-processed count.
    started = time.perf_counter()
    job = await session.get(BatchJob, item.batch_job_id)
    config = await _get_model_config(session, job.model_name)
    payload = item.input_payload or {}
    prompt = payload.get("prompt")
    max_tokens = payload.get("max_tokens") or _config_max_tokens(config)
    temperature = payload.get("temperature", _DEFAULT_TEMPERATURE)
    # Close the read transaction before the (slow) model call. Rows stay loaded.
    await session.commit()

    if not prompt:
        _fail(item, "input_payload missing 'prompt'")
    else:
        try:
            completion = await _complete_with_retry(
                client,
                model=job.model_name,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            item.output_payload = {
                "output": completion.output,
                "model": completion.model,
                "usage": {
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                },
            }
            item.status = ItemStatus.COMPLETED.value
            item.error_message = None
        except VLLMError as exc:
            _fail(item, str(exc))

    terminal_status = _update_job_progress(job, item.status)
    await session.commit()

    observe_batch_item(item.status, time.perf_counter() - started)
    if terminal_status is not None:
        observe_batch_job(terminal_status)

    logger.info(
        "processed item",
        extra={
            "item_id": str(item.id),
            "job_id": str(item.batch_job_id),
            "status": item.status,
        },
    )


async def _complete_with_retry(client: VLLMClient, **kwargs):
    """One retry on a transient error; non-transient errors propagate as-is."""
    try:
        return await client.complete(**kwargs)
    except _TRANSIENT_ERRORS as exc:
        logger.warning("transient vLLM error, retrying once", extra={"error": str(exc)})
        return await client.complete(**kwargs)


async def _get_model_config(
    session: AsyncSession, model_name: str
) -> ModelConfig | None:
    stmt = select(ModelConfig).where(ModelConfig.model_name == model_name).limit(1)
    return (await session.execute(stmt)).scalars().first()


def _config_max_tokens(config: ModelConfig | None) -> int:
    return config.max_tokens_default if config is not None else _DEFAULT_MAX_TOKENS


def _fail(item: BatchJobItem, message: str) -> None:
    item.status = ItemStatus.FAILED.value
    item.error_message = message


def _update_job_progress(job: BatchJob, item_status: str) -> str | None:
    """Bump the job's progress counters; return its terminal status if this
    item was the last one (so the caller can count the job), else None."""
    if item_status == ItemStatus.COMPLETED.value:
        job.completed_items += 1
    elif item_status == ItemStatus.FAILED.value:
        job.failed_items += 1

    if job.completed_items + job.failed_items >= job.total_items:
        job.completed_at = datetime.now(UTC)
        # All items processed: failed only if none succeeded; otherwise
        # completed (partial failures are recorded in failed_items).
        job.status = (
            JobStatus.COMPLETED.value
            if job.completed_items > 0
            else JobStatus.FAILED.value
        )
        return job.status
    return None
