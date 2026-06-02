"""Unit tests for the shared Prometheus metrics.

Metrics are process-global, so tests assert on before/after deltas via
REGISTRY.get_sample_value rather than absolute values — order-independent.
"""

import urllib.request

from prometheus_client import REGISTRY

from aiinfra.observability.metrics import (
    observe_batch_item,
    observe_batch_job,
    observe_inference,
    render_latest,
    set_queue_lag,
    start_metrics_server,
)

_COUNT = "aiinfra_inference_requests_total"
_DURATION_COUNT = "aiinfra_inference_request_duration_seconds_count"
_JOBS = "aiinfra_batch_jobs_total"
_ITEM_DURATION_COUNT = "aiinfra_batch_item_processing_duration_seconds_count"
_QUEUE_LAG = "aiinfra_batch_queue_lag_seconds"


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


def test_observe_batch_job_increments_counter_by_status():
    before = _sample(_JOBS, "completed")

    observe_batch_job("completed")

    assert _sample(_JOBS, "completed") == before + 1


def test_observe_batch_item_records_duration_by_status():
    before = _sample(_ITEM_DURATION_COUNT, "failed")

    observe_batch_item("failed", 0.5)

    assert _sample(_ITEM_DURATION_COUNT, "failed") == before + 1


def test_set_queue_lag_sets_gauge_value():
    set_queue_lag(12.5)

    assert REGISTRY.get_sample_value(_QUEUE_LAG) == 12.5


def test_metrics_server_serves_exposition_over_http():
    # Port 0 lets the OS assign a free port; read the real one back off the
    # server so the test never collides with a port already in use.
    server = start_metrics_server(0, addr="127.0.0.1")
    try:
        observe_inference("ok", 0.07)
        url = f"http://127.0.0.1:{server.server_port}/metrics"
        with urllib.request.urlopen(url, timeout=5) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode()

        assert status == 200
        assert _COUNT in body
        assert content_type.startswith("text/plain")
    finally:
        server.shutdown()
        server.server_close()
