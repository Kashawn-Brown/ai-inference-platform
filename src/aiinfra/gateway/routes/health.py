"""Health and readiness routes.

`/healthz` is liveness only — confirms the process is responding, with no
dependency checks (so an orchestrator won't kill the process while a dependency
is briefly down). `/readyz` is readiness — it reports whether the gateway can
actually serve traffic, checking vLLM reachability and DB connectivity.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aiinfra.db.engine import check_database
from aiinfra.gateway.deps import get_vllm_client
from aiinfra.vllm.client import VLLMClient

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(
    client: Annotated[VLLMClient, Depends(get_vllm_client)],
) -> JSONResponse:
    # Independent checks — run them concurrently.
    vllm_ok, db_ok = await asyncio.gather(client.ping(), check_database())
    checks = {"vllm": vllm_ok, "database": db_ok}
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not ready", "checks": checks},
    )
