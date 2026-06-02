"""Prometheus metrics — shared definitions for gateway and worker.

Phase 1 covers live inference: request count, request duration, and error count.
These ride on one labeled counter plus a histogram — the error count is the
non-"ok" slice of the counter (`status != "ok"`), so there's no separate error
metric to keep in sync. The worker adds its own metrics against the same default
registry in later phases.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Latency buckets tuned for LLM inference: sub-second through the 30s timeout.
_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)

# Counter name omits the `_total` suffix; the client appends it on exposition.
inference_requests = Counter(
    "aiinfra_inference_requests",
    "Live inference requests by outcome.",
    labelnames=("status",),
)

inference_request_duration = Histogram(
    "aiinfra_inference_request_duration_seconds",
    "Live inference request latency, gateway-measured.",
    labelnames=("status",),
    buckets=_DURATION_BUCKETS,
)


def observe_inference(status: str, duration_seconds: float) -> None:
    """Record one completed inference request (success or mapped failure).

    `status` is "ok" or the client error class name, matching the per-request
    log line's `status` field so logs and metrics line up.
    """
    inference_requests.labels(status=status).inc()
    inference_request_duration.labels(status=status).observe(duration_seconds)


def render_latest() -> tuple[bytes, str]:
    """Current metrics in Prometheus text exposition format, plus content type.

    Framework-free so the worker's future scrape endpoint can reuse it.
    """
    return generate_latest(), CONTENT_TYPE_LATEST
