"""Health and readiness routes.

`/healthz` is liveness only — confirms the process is responding. `/readyz`
arrives in Phase 1 and additionally checks vLLM reachability and DB connectivity.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}
