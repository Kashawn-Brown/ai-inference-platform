"""Unit tests for the shared Prometheus metrics.

Metrics are process-global, so tests assert on before/after deltas via
REGISTRY.get_sample_value rather than absolute values — order-independent.
"""

from prometheus_client import REGISTRY

from aiinfra.observability.metrics import observe_inference, render_latest

_COUNT = "aiinfra_inference_requests_total"
_DURATION_COUNT = "aiinfra_inference_request_duration_seconds_count"


def _sample(name: str, status: str) -> float:
    value = REGISTRY.get_sample_value(name, {"status": status})
    return value or 0.0


def test_observe_increments_request_counter_for_status():
    before = _sample(_COUNT, "ok")

    observe_inference("ok", 0.12)

    assert _sample(_COUNT, "ok") == before + 1


def test_observe_records_a_duration_observation():
    before = _sample(_DURATION_COUNT, "ok")

    observe_inference("ok", 0.34)

    assert _sample(_DURATION_COUNT, "ok") == before + 1


def test_error_statuses_are_counted_separately():
    before = _sample(_COUNT, "VLLMTimeoutError")

    observe_inference("VLLMTimeoutError", 30.0)

    assert _sample(_COUNT, "VLLMTimeoutError") == before + 1


def test_render_latest_emits_exposition_text():
    observe_inference("ok", 0.05)
    payload, content_type = render_latest()

    text = payload.decode()
    assert _COUNT in text
    assert "aiinfra_inference_request_duration_seconds_bucket" in text
    assert content_type.startswith("text/plain")
