"""Unit tests for the vLLM client.

httpx.MockTransport drives responses (and failures) without a network, so these
stay fast and dependency-free at the network layer. Async tests run under
pytest-asyncio's auto mode (configured in pyproject.toml) — no per-test marker.
"""

import json

import httpx
import pytest

from aiinfra.vllm.client import (
    VLLMClient,
    VLLMCompletion,
    VLLMConnectionError,
    VLLMResponseError,
    VLLMTimeoutError,
)

# A well-formed OpenAI-compatible chat completion response.
_OK_BODY = {
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "choices": [{"message": {"role": "assistant", "content": "Hello there."}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
}


def _client(handler) -> VLLMClient:
    return VLLMClient(
        base_url="http://vllm:8000",
        model_name="Qwen/Qwen2.5-1.5B-Instruct",
        timeout_ms=30000,
        transport=httpx.MockTransport(handler),
    )


async def test_complete_parses_output_and_usage():
    client = _client(lambda req: httpx.Response(200, json=_OK_BODY))

    result = await client.complete(prompt="hi", max_tokens=16, temperature=0.7)
    await client.aclose()

    assert result == VLLMCompletion(
        model="Qwen/Qwen2.5-1.5B-Instruct",
        output="Hello there.",
        prompt_tokens=11,
        completion_tokens=4,
    )


async def test_complete_sends_chat_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json=_OK_BODY)

    client = _client(handler)
    await client.complete(prompt="explain DNS", max_tokens=64, temperature=0.2)
    await client.aclose()

    assert seen["url"] == "http://vllm:8000/v1/chat/completions"
    assert seen["json"] == {
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "messages": [{"role": "user", "content": "explain DNS"}],
        "max_tokens": 64,
        "temperature": 0.2,
    }


async def test_complete_model_override_sets_payload_model():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json=_OK_BODY)

    client = _client(handler)
    await client.complete(
        prompt="hi", max_tokens=16, temperature=0.7, model="other/model"
    )
    await client.aclose()

    assert seen["json"]["model"] == "other/model"


async def test_timeout_maps_to_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = _client(handler)
    with pytest.raises(VLLMTimeoutError):
        await client.complete(prompt="hi", max_tokens=16, temperature=0.7)
    await client.aclose()


async def test_connection_failure_maps_to_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(handler)
    with pytest.raises(VLLMConnectionError):
        await client.complete(prompt="hi", max_tokens=16, temperature=0.7)
    await client.aclose()


async def test_non_2xx_maps_to_response_error_with_status():
    client = _client(lambda req: httpx.Response(503, text="unavailable"))

    with pytest.raises(VLLMResponseError) as excinfo:
        await client.complete(prompt="hi", max_tokens=16, temperature=0.7)
    await client.aclose()

    assert excinfo.value.status_code == 503


async def test_malformed_body_maps_to_response_error():
    # 200 OK but missing the choices/usage structure entirely.
    client = _client(lambda req: httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(VLLMResponseError):
        await client.complete(prompt="hi", max_tokens=16, temperature=0.7)
    await client.aclose()


async def test_ping_true_on_healthy():
    client = _client(lambda req: httpx.Response(200))

    assert await client.ping() is True
    await client.aclose()


async def test_ping_false_on_non_2xx():
    client = _client(lambda req: httpx.Response(503))

    assert await client.ping() is False
    await client.aclose()


async def test_ping_false_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(handler)
    assert await client.ping() is False
    await client.aclose()
