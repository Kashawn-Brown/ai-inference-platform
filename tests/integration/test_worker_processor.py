"""Integration tests for the worker processing step.

A claimed item is run through `process_item` with a scripted fake vLLM client
(no network) against the test DB. Covers success, non-transient failure,
retry-once-then-succeed, retry-exhausted, partial-failure job status, the
missing-prompt short-circuit, and model/serving-param resolution.
"""

from types import SimpleNamespace

from aiinfra.db.models import BatchJob, BatchJobItem, ItemStatus, JobStatus
from aiinfra.vllm.client import (
    VLLMCompletion,
    VLLMConnectionError,
    VLLMResponseError,
    VLLMTimeoutError,
)
from aiinfra.worker.claim import claim_next_item
from aiinfra.worker.processor import process_item
from tests.integration.conftest import ACTIVE_MODEL


class _FakeClient:
    """Returns/raises a scripted behavior per call; records call kwargs."""

    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = []

    async def complete(self, *, prompt, max_tokens, temperature, model=None):
        self.calls.append(
            SimpleNamespace(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
            )
        )
        behavior = self._behaviors[len(self.calls) - 1]
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _completion(output="hello"):
    return VLLMCompletion(
        model=ACTIVE_MODEL, output=output, prompt_tokens=3, completion_tokens=5
    )


async def _make_job(session, *, payloads, model_name=ACTIVE_MODEL):
    job = BatchJob(
        name="job",
        model_name=model_name,
        job_type="inference",
        status=JobStatus.QUEUED.value,
        total_items=len(payloads),
    )
    session.add(job)
    await session.flush()
    for i, payload in enumerate(payloads):
        session.add(
            BatchJobItem(
                batch_job_id=job.id,
                item_index=i,
                input_payload=payload,
                status=ItemStatus.QUEUED.value,
            )
        )
    await session.commit()
    return job


async def test_process_completes_item(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, payloads=[{"prompt": "hi"}])

    client = _FakeClient([_completion("the answer")])
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    async with session_factory() as check:
        it = await check.get(BatchJobItem, item.id)
        jb = await check.get(BatchJob, job.id)

    assert it.status == ItemStatus.COMPLETED.value
    assert it.output_payload["output"] == "the answer"
    assert it.output_payload["usage"]["completion_tokens"] == 5
    assert it.error_message is None
    assert jb.completed_items == 1 and jb.failed_items == 0
    assert jb.status == JobStatus.COMPLETED.value
    assert jb.completed_at is not None
    assert client.calls[0].model == ACTIVE_MODEL  # job's model, not env


async def test_non_transient_failure_is_recorded_without_retry(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, payloads=[{"prompt": "hi"}])

    client = _FakeClient([VLLMResponseError("bad", status_code=500)])
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    async with session_factory() as check:
        it = await check.get(BatchJobItem, item.id)
        jb = await check.get(BatchJob, job.id)

    assert it.status == ItemStatus.FAILED.value
    assert it.error_message
    assert len(client.calls) == 1  # non-transient: no retry
    assert jb.failed_items == 1 and jb.completed_items == 0
    assert jb.status == JobStatus.FAILED.value  # all items failed
    assert jb.completed_at is not None


async def test_retries_once_on_transient_then_succeeds(session_factory):
    async with session_factory() as setup:
        await _make_job(setup, payloads=[{"prompt": "hi"}])

    client = _FakeClient([VLLMTimeoutError("slow"), _completion("ok")])
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    async with session_factory() as check:
        it = await check.get(BatchJobItem, item.id)

    assert it.status == ItemStatus.COMPLETED.value
    assert len(client.calls) == 2  # one retry


async def test_transient_error_twice_fails(session_factory):
    async with session_factory() as setup:
        await _make_job(setup, payloads=[{"prompt": "hi"}])

    client = _FakeClient([VLLMConnectionError("down"), VLLMConnectionError("down")])
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    async with session_factory() as check:
        it = await check.get(BatchJobItem, item.id)

    assert it.status == ItemStatus.FAILED.value
    assert it.error_message
    assert len(client.calls) == 2  # original + one retry, then give up


async def test_partial_failure_marks_job_completed(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, payloads=[{"prompt": "a"}, {"prompt": "b"}])

    client = _FakeClient([_completion("ok"), VLLMResponseError("bad", status_code=500)])
    async with session_factory() as s:
        first = await claim_next_item(s)
        await process_item(s, client, first)
        second = await claim_next_item(s)
        await process_item(s, client, second)

    async with session_factory() as check:
        jb = await check.get(BatchJob, job.id)

    assert jb.completed_items == 1 and jb.failed_items == 1
    assert jb.status == JobStatus.COMPLETED.value  # ran to completion
    assert jb.completed_at is not None


async def test_missing_prompt_fails_without_calling_vllm(session_factory):
    async with session_factory() as setup:
        job = await _make_job(setup, payloads=[{}])

    client = _FakeClient([])  # complete() must never be called
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    async with session_factory() as check:
        it = await check.get(BatchJobItem, item.id)
        jb = await check.get(BatchJob, job.id)

    assert it.status == ItemStatus.FAILED.value
    assert "prompt" in it.error_message
    assert client.calls == []
    assert jb.status == JobStatus.FAILED.value


async def test_resolves_max_tokens_from_config(session_factory):
    # No max_tokens in the payload -> falls back to the model config's default
    # (the seeded ACTIVE_MODEL has max_tokens_default=512).
    async with session_factory() as setup:
        await _make_job(setup, payloads=[{"prompt": "hi"}])

    client = _FakeClient([_completion()])
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    assert client.calls[0].max_tokens == 512


async def test_payload_overrides_generation_params(session_factory):
    async with session_factory() as setup:
        await _make_job(
            setup, payloads=[{"prompt": "hi", "max_tokens": 64, "temperature": 0.1}]
        )

    client = _FakeClient([_completion()])
    async with session_factory() as s:
        item = await claim_next_item(s)
        await process_item(s, client, item)

    assert client.calls[0].max_tokens == 64
    assert client.calls[0].temperature == 0.1
