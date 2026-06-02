"""POST /v1/inference — single synchronous inference request.

Validates the request, calls the shared vLLM client, maps the client's typed
failures to HTTP status codes, and emits exactly one structured log line per
request (success or failure) carrying request_id, status, and latency.
"""

import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from aiinfra.gateway.deps import get_vllm_client
from aiinfra.observability.metrics import observe_inference
from aiinfra.schemas.inference import InferenceRequest, InferenceResponse, Usage
from aiinfra.vllm.client import (
    VLLMClient,
    VLLMConnectionError,
    VLLMResponseError,
    VLLMTimeoutError,
)

logger = logging.getLogger("aiinfra.gateway.inference")
router = APIRouter(tags=["inference"])

# Upstream failure -> HTTP status. The client already distinguishes the modes;
# here we just translate to the gateway's contract with the caller.
#   timeout    -> 504 Gateway Timeout    (upstream too slow)
#   unreachable-> 503 Service Unavailable (upstream down)
#   bad reply  -> 502 Bad Gateway        (upstream returned error/garbage)
_ERROR_MAP = {
    VLLMTimeoutError: (status.HTTP_504_GATEWAY_TIMEOUT, "Model request timed out."),
    VLLMConnectionError: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Model server unreachable.",
    ),
    VLLMResponseError: (
        status.HTTP_502_BAD_GATEWAY,
        "Model server returned an invalid response.",
    ),
}


@router.post("/v1/inference", response_model=InferenceResponse)
async def create_inference(
    payload: InferenceRequest,
    client: Annotated[VLLMClient, Depends(get_vllm_client)],
) -> InferenceResponse:
    request_id = str(uuid.uuid4())
    start = time.perf_counter()

    try:
        completion = await client.complete(
            prompt=payload.prompt,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
        )
    except (VLLMTimeoutError, VLLMConnectionError, VLLMResponseError) as exc:
        elapsed_s = time.perf_counter() - start
        status_label = type(exc).__name__
        http_status, detail = _ERROR_MAP[type(exc)]
        observe_inference(status_label, elapsed_s)
        _log_request(
            request_id,
            status_label=status_label,
            latency_ms=int(elapsed_s * 1000),
            level=logging.WARNING,
        )
        raise HTTPException(status_code=http_status, detail=detail) from exc

    elapsed_s = time.perf_counter() - start
    latency_ms = int(elapsed_s * 1000)
    observe_inference("ok", elapsed_s)
    _log_request(
        request_id,
        status_label="ok",
        latency_ms=latency_ms,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )
    return InferenceResponse(
        request_id=request_id,
        model=completion.model,
        output=completion.output,
        usage=Usage(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
        ),
        latency_ms=latency_ms,
    )


def _log_request(
    request_id: str,
    *,
    status_label: str,
    latency_ms: int,
    level: int = logging.INFO,
    **fields,
) -> None:
    logger.log(
        level,
        "inference request",
        extra={
            "request_id": request_id,
            "status": status_label,
            "latency_ms": latency_ms,
            **fields,
        },
    )
