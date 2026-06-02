"""Unit tests for the inference API schemas.

Validation only — no I/O, so these are plain sync tests.
"""

import pytest
from pydantic import ValidationError

from aiinfra.schemas.inference import InferenceRequest, InferenceResponse, Usage


def test_request_applies_defaults():
    req = InferenceRequest(prompt="hello")

    assert req.max_tokens == 512
    assert req.temperature == 0.7


def test_request_rejects_empty_prompt():
    with pytest.raises(ValidationError):
        InferenceRequest(prompt="")


def test_request_requires_prompt():
    with pytest.raises(ValidationError):
        InferenceRequest()


@pytest.mark.parametrize("bad_max_tokens", [0, -1, 9000])
def test_request_rejects_out_of_range_max_tokens(bad_max_tokens):
    with pytest.raises(ValidationError):
        InferenceRequest(prompt="hi", max_tokens=bad_max_tokens)


@pytest.mark.parametrize("bad_temperature", [-0.1, 2.1])
def test_request_rejects_out_of_range_temperature(bad_temperature):
    with pytest.raises(ValidationError):
        InferenceRequest(prompt="hi", temperature=bad_temperature)


def test_response_round_trips_with_nested_usage():
    resp = InferenceResponse(
        request_id="abc-123",
        model="Qwen/Qwen2.5-1.5B-Instruct",
        output="Hello there.",
        usage=Usage(prompt_tokens=11, completion_tokens=4),
        latency_ms=142,
    )

    dumped = resp.model_dump()
    assert dumped["usage"] == {"prompt_tokens": 11, "completion_tokens": 4}
    assert dumped["latency_ms"] == 142
    # Re-parsing the dumped dict yields an equal model.
    assert InferenceResponse.model_validate(dumped) == resp
