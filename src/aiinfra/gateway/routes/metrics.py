"""GET /metrics — Prometheus scrape endpoint for the gateway.

Excluded from the OpenAPI schema: it's an infra surface for Prometheus, not part
of the public API. The actual metrics are defined in aiinfra.observability.metrics.
"""

from fastapi import APIRouter, Response

from aiinfra.observability.metrics import render_latest

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)
