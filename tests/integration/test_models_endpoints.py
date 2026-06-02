"""Integration tests for the read-only model-config endpoints."""

from tests.integration.conftest import ACTIVE_MODEL, INACTIVE_MODEL


def test_list_returns_only_active(client):
    resp = client.get("/v1/models")

    assert resp.status_code == 200
    names = [c["model_name"] for c in resp.json()]
    assert names == [ACTIVE_MODEL]  # the inactive config is filtered out


def test_detail_returns_active_config(client):
    resp = client.get(f"/v1/models/{ACTIVE_MODEL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["model_name"] == ACTIVE_MODEL
    assert body["is_active"] is True
    assert body["provider_type"] == "vllm"


def test_detail_returns_inactive_config(client):
    # Detail returns whatever exists by name, active or not.
    resp = client.get(f"/v1/models/{INACTIVE_MODEL}")

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_detail_unknown_name_is_404(client):
    resp = client.get("/v1/models/nope/missing-model")

    assert resp.status_code == 404
