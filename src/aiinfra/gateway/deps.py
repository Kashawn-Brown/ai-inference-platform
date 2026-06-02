"""FastAPI dependencies for the gateway.

Thin accessors that hand route handlers the shared resources set up in the app
lifespan. Keeping them here (rather than reaching into app.state inline) gives
tests a single seam to override.
"""

from fastapi import Request

from aiinfra.vllm.client import VLLMClient


def get_vllm_client(request: Request) -> VLLMClient:
    return request.app.state.vllm_client
