"""Unit tests for the batch API schemas. Validation only — no I/O."""

import pytest
from pydantic import ValidationError

from aiinfra.schemas.batch import BatchJobCreate


def test_applies_defaults():
    job = BatchJobCreate(name="nightly", items=[{"input_payload": {"prompt": "hi"}}])

    assert job.job_type == "inference"
    assert job.model is None
    assert job.submitted_by is None


def test_rejects_empty_items():
    with pytest.raises(ValidationError):
        BatchJobCreate(name="nightly", items=[])


def test_rejects_empty_name():
    with pytest.raises(ValidationError):
        BatchJobCreate(name="", items=[{"input_payload": {"prompt": "hi"}}])


def test_requires_items():
    with pytest.raises(ValidationError):
        BatchJobCreate(name="nightly")


def test_carries_optional_model_and_submitter():
    job = BatchJobCreate(
        name="bench",
        model="custom/model",
        submitted_by="benchmark-runner",
        items=[{"input_payload": {"prompt": "hi"}}],
    )

    assert job.model == "custom/model"
    assert job.submitted_by == "benchmark-runner"
    assert job.items[0].input_payload == {"prompt": "hi"}
