"""FastAPI gateway entrypoint.

Builds the FastAPI app and mounts route modules. Run locally with:
    uv run uvicorn aiinfra.gateway.main:app --reload

Lifespan owns process-wide setup: structured logging and a single shared vLLM
client (one connection pool reused across requests, closed on shutdown).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from aiinfra.config import get_settings
from aiinfra.gateway.routes import health, inference, metrics
from aiinfra.logging import configure_logging
from aiinfra.vllm.client import VLLMClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app.state.vllm_client = VLLMClient.from_settings(settings)
    try:
        yield
    finally:
        await app.state.vllm_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="aiinfra gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(inference.router)
    app.include_router(metrics.router)
    return app


app = create_app()
