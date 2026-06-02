"""Integration tests for /healthz and /readyz.

/readyz fans out to two dependency checks. The vLLM client is overridden with a
fake whose ping result we control; the DB check is monkeypatched, so neither
test needs a real vLLM or Postgres.
"""

import pytest
from fastapi.testclient import TestClient

from aiinfra.gateway.deps import get_vllm_client
from aiinfra.gateway.main import create_app


class _PingFake:
    """Stand-in for VLLMClient exposing only the readiness probe."""

    def __init__(self, ok: bool):
        self._ok = ok

    async def ping(self) -> bool:
        return self._ok


def _db_check_returning(value: bool):
    async def _check() -> bool:
        return value

    return _check


def _app_with(*, vllm_ok: bool) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_vllm_client] = lambda: _PingFake(vllm_ok)
    return TestClient(app)


def test_healthz_is_liveness_only():
    with _app_with(vllm_ok=True) as client:
        resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ready_when_both_dependencies_up(monkeypatch):
    monkeypatch.setattr(
        "aiinfra.gateway.routes.health.check_database", _db_check_returning(True)
    )

    with _app_with(vllm_ok=True) as client:
        resp = client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ready",
        "checks": {"vllm": True, "database": True},
    }


@pytest.mark.parametrize(
    ("vllm_ok", "db_ok"),
    [(False, True), (True, False), (False, False)],
)
def test_readyz_not_ready_when_a_dependency_is_down(monkeypatch, vllm_ok, db_ok):
    monkeypatch.setattr(
        "aiinfra.gateway.routes.health.check_database", _db_check_returning(db_ok)
    )

    with _app_with(vllm_ok=vllm_ok) as client:
        resp = client.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not ready"
    assert body["checks"] == {"vllm": vllm_ok, "database": db_ok}
