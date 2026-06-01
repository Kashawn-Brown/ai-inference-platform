"""Async vLLM client.

Wraps the OpenAI-compatible vLLM HTTP API for live inference. Shared by the
gateway (Phase 1) and, later, the batch worker (Phase 2) — the worker calls
vLLM directly, never through the gateway.

This module is the boundary where vLLM's failure modes are turned into typed
errors. Transport problems (timeout, refused connection) and protocol problems
(non-2xx, malformed body) become `VLLMError` subclasses so callers map them to
HTTP responses (gateway) or item failures (worker) without reaching into httpx
internals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from aiinfra.config import Settings

logger = logging.getLogger("aiinfra.vllm.client")

# vLLM exposes the OpenAI-compatible surface; chat/completions is the right call
# for an instruct-tuned model since it applies the chat template server-side.
_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


class VLLMError(Exception):
    """Base class for all vLLM client failures."""


class VLLMTimeoutError(VLLMError):
    """The request to vLLM exceeded the configured timeout."""


class VLLMConnectionError(VLLMError):
    """vLLM was unreachable (connection refused, DNS, transport error)."""


class VLLMResponseError(VLLMError):
    """vLLM returned a non-2xx status or an unparseable body."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VLLMCompletion:
    """Result of a single completion call.

    The client's return contract — deliberately narrower than the public
    `InferenceResponse`. request_id and latency_ms are the gateway's concern,
    not the client's.
    """

    model: str
    output: str
    prompt_tokens: int
    completion_tokens: int


class VLLMClient:
    """Async client for a single vLLM server.

    Holds one `httpx.AsyncClient` for connection reuse. Construct via
    `from_settings` in process code; pass `transport` directly in tests to
    drive responses without a network.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_ms: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model_name = model_name
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_ms / 1000),  # ms -> seconds
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> VLLMClient:
        return cls(
            base_url=settings.vllm_base_url,
            model_name=settings.vllm_model_name,
            timeout_ms=settings.vllm_timeout_ms,
        )

    async def complete(
        self, *, prompt: str, max_tokens: int, temperature: float
    ) -> VLLMCompletion:
        """Run a single chat completion and return the model output + usage."""
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = await self._client.post(_CHAT_COMPLETIONS_PATH, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("vllm request timed out", extra={"model": self._model_name})
            raise VLLMTimeoutError(
                f"vLLM request timed out for model {self._model_name}"
            ) from exc
        except httpx.HTTPError as exc:
            # Covers connect/read/transport errors that aren't timeouts.
            logger.warning(
                "vllm connection error",
                extra={"model": self._model_name, "error": str(exc)},
            )
            raise VLLMConnectionError(f"could not reach vLLM: {exc}") from exc

        if response.status_code >= 400:
            logger.warning(
                "vllm returned error status",
                extra={"status_code": response.status_code},
            )
            raise VLLMResponseError(
                f"vLLM returned {response.status_code}",
                status_code=response.status_code,
            )

        return self._parse(response)

    def _parse(self, response: httpx.Response) -> VLLMCompletion:
        try:
            data = response.json()
            choice = data["choices"][0]
            usage = data["usage"]
            return VLLMCompletion(
                model=data.get("model", self._model_name),
                output=choice["message"]["content"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("vllm returned malformed body", extra={"error": str(exc)})
            raise VLLMResponseError(f"malformed vLLM response: {exc}") from exc

    async def aclose(self) -> None:
        """Close the underlying connection pool. Call on process shutdown."""
        await self._client.aclose()
