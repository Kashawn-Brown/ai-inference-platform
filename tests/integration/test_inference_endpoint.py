"""Integration tests for POST /v1/inference.

The vLLM client is replaced via dependency override so these exercise the route
itself — validation, error-to-status mapping, and response shaping. The client's
network behavior is covered separately in tests/unit/test_vllm_client.py.

TestClient is used as a context manager so the app lifespan runs (the real
client created there makes no network calls — the override intercepts first).
"""

import pytest
from fastapi.testclient import TestClient

from aiinfra.gateway.deps import get_vllm_client
from aiinfra.gateway.main import create_app
from aiinfra.vllm.client import (
    VLLMCompletion,
    VLLMConnectionError,
    VLLMResponseError,
    VLLMTimeoutError,
)


class _FakeClient:
    """Stand-in for VLLMClient: returns a fixed completion or raises."""

    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error

    async def complete(self, *, prompt, max_tokens, temperature):
        if self._error is not None:
            raise self._error
        return self._result


def _client_with(fake: _FakeClient) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_vllm_client] = lambda: fake
    return TestClient(app)


_COMPLETION = VLLMCompletion(
    model="Qwen/Qwen2.5-1.5B-Instruct",
    output="Hello there.",
    prompt_tokens=11,
    completion_tokens=4,
)


def test_happy_path_returns_shaped_response():
    with _client_with(_FakeClient(result=_COMPLETION)) as client:
        resp = client.post("/v1/inference", json={"prompt": "hi"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "Qwen/Qwen2.5-1.5B-Instruct"
    assert body["output"] == "Hello there."
    assert body["usage"] == {"prompt_tokens": 11, "completion_tokens": 4}
    assert body["latency_ms"] >= 0
    # request_id is a generated, non-empty correlation id.
    assert body["request_id"]


def test_empty_prompt_is_rejected_before_the_model():
    with _client_with(_FakeClient(result=_COMPLETION)) as client:
        resp = client.post("/v1/inference", json={"prompt": ""})

    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (VLLMTimeoutError("slow"), 504),
        (VLLMConnectionError("down"), 503),
        (VLLMResponseError("bad", status_code=500), 502),
    ],
)
def test_upstream_failures_map_to_status(error, expected_status):
    with _client_with(_FakeClient(error=error)) as client:
        resp = client.post("/v1/inference", json={"prompt": "hi"})

    assert resp.status_code == expected_status
    assert resp.json()["detail"]
