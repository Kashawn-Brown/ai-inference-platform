"""FastAPI gateway entrypoint.

Builds the FastAPI app and mounts route modules. Run locally with:
    uv run uvicorn aiinfra.gateway.main:app --reload
"""

from fastapi import FastAPI

from aiinfra.gateway.routes import health


def create_app() -> FastAPI:
    app = FastAPI(title="aiinfra gateway", version="0.1.0")
    app.include_router(health.router)
    return app


app = create_app()
