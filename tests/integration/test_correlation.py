"""Integration tests for gateway correlation-ID propagation.

The CorrelationIdMiddleware should put an X-Request-ID on every response —
generated when absent, echoed when the caller supplies one — and the inference
route should reuse that same id in its response body.
"""

from fastapi.testclient import TestClient

from aiinfra.gateway.deps import get_vllm_client
from aiinfra.gateway.main import create_app
from aiinfra.vllm.client import VLLMCompletion


def test_response_has_generated_request_id_header():
    # /healthz is dependency-free, so this exercises the middleware in isolation.
    client = TestClient(create_app())
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")


def test_inbound_request_id_is_echoed():
    client = TestClient(create_app())
    resp = client.get("/healthz", headers={"X-Request-ID": "caller-123"})

    assert resp.headers.get("X-Request-ID") == "caller-123"


def test_inference_body_request_id_matches_header():
    completion = VLLMCompletion(
        model="m", output="o", prompt_tokens=1, completion_tokens=1
    )

    class _Fake:
        async def complete(self, *, prompt, max_tokens, temperature):
            return completion

    app = create_app()
    app.dependency_overrides[get_vllm_client] = lambda: _Fake()
    with TestClient(app) as client:
        resp = client.post("/v1/inference", json={"prompt": "hi"})

    assert resp.status_code == 200
    assert resp.json()["request_id"] == resp.headers["X-Request-ID"]
