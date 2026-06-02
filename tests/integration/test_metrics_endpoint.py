"""Integration tests for the gateway /metrics scrape endpoint.

Verifies the endpoint serves Prometheus exposition and that a completed
inference request is reflected in the counter (end-to-end through the route).
"""

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from aiinfra.gateway.deps import get_vllm_client
from aiinfra.gateway.main import create_app
from aiinfra.vllm.client import VLLMCompletion

from .test_inference_endpoint import _FakeClient

_COUNT = "aiinfra_inference_requests_total"
_COMPLETION = VLLMCompletion(
    model="Qwen/Qwen2.5-1.5B-Instruct",
    output="hi",
    prompt_tokens=3,
    completion_tokens=1,
)


def _client_with(fake: _FakeClient) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_vllm_client] = lambda: fake
    return TestClient(app)


def test_metrics_endpoint_serves_exposition():
    with _client_with(_FakeClient(result=_COMPLETION)) as client:
        resp = client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert _COUNT in resp.text


def test_successful_request_increments_ok_counter():
    before = REGISTRY.get_sample_value(_COUNT, {"status": "ok"}) or 0.0

    with _client_with(_FakeClient(result=_COMPLETION)) as client:
        assert client.post("/v1/inference", json={"prompt": "hi"}).status_code == 200

    after = REGISTRY.get_sample_value(_COUNT, {"status": "ok"}) or 0.0
    assert after == before + 1
