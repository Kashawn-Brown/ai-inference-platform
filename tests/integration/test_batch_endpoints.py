"""Integration tests for the batch job endpoints.

Driven through the API against the test DB (see conftest `client`). Model
resolution, validation, pagination, and not-found behavior are covered here;
item processing is the worker's job, not the gateway's.
"""

import uuid

from tests.integration.conftest import ACTIVE_MODEL, INACTIVE_MODEL


def _submit(client, *, name="job", model=None, n_items=1, submitted_by=None):
    body = {
        "name": name,
        "items": [{"input_payload": {"prompt": f"p{i}"}} for i in range(n_items)],
    }
    if model is not None:
        body["model"] = model
    if submitted_by is not None:
        body["submitted_by"] = submitted_by
    return client.post("/v1/batch/jobs", json=body)


def test_submit_stamps_active_model_when_omitted(client):
    resp = _submit(client, name="nightly", n_items=3, submitted_by="dev-cli")

    assert resp.status_code == 201
    body = resp.json()
    assert body["model_name"] == ACTIVE_MODEL
    assert body["status"] == "queued"
    assert body["total_items"] == 3
    assert body["completed_items"] == 0
    assert body["failed_items"] == 0
    assert body["submitted_by"] == "dev-cli"
    assert body["id"]


def test_submit_uses_provided_model_even_if_inactive(client):
    resp = _submit(client, model=INACTIVE_MODEL)

    assert resp.status_code == 201
    assert resp.json()["model_name"] == INACTIVE_MODEL


def test_submit_rejects_unknown_model(client):
    resp = _submit(client, model="nope/does-not-exist")

    assert resp.status_code == 422


def test_submit_rejects_empty_items(client):
    resp = client.post("/v1/batch/jobs", json={"name": "x", "items": []})

    assert resp.status_code == 422


def test_get_job_returns_record(client):
    job_id = _submit(client, name="findme").json()["id"]

    resp = client.get(f"/v1/batch/jobs/{job_id}")

    assert resp.status_code == 200
    assert resp.json()["name"] == "findme"


def test_get_job_unknown_id_is_404(client):
    resp = client.get(f"/v1/batch/jobs/{uuid.uuid4()}")

    assert resp.status_code == 404


def test_get_job_malformed_id_is_422(client):
    resp = client.get("/v1/batch/jobs/not-a-uuid")

    assert resp.status_code == 422


def test_list_jobs_filters_by_status(client):
    _submit(client, name="a")
    _submit(client, name="b")

    queued = client.get("/v1/batch/jobs", params={"status": "queued"}).json()
    completed = client.get("/v1/batch/jobs", params={"status": "completed"}).json()

    assert len(queued["jobs"]) == 2
    assert completed["jobs"] == []


def test_list_jobs_rejects_unknown_status(client):
    resp = client.get("/v1/batch/jobs", params={"status": "bogus"})

    assert resp.status_code == 422


def test_list_jobs_paginates(client):
    submitted = {_submit(client, name=f"job{i}").json()["id"] for i in range(3)}

    page1 = client.get("/v1/batch/jobs", params={"limit": 2}).json()
    assert len(page1["jobs"]) == 2
    assert page1["next_cursor"]

    page2 = client.get(
        "/v1/batch/jobs", params={"limit": 2, "cursor": page1["next_cursor"]}
    ).json()
    assert len(page2["jobs"]) == 1
    assert page2["next_cursor"] is None

    seen = [j["id"] for j in page1["jobs"]] + [j["id"] for j in page2["jobs"]]
    assert set(seen) == submitted  # full coverage, no overlap
    assert len(seen) == 3


def test_list_jobs_rejects_invalid_cursor(client):
    resp = client.get("/v1/batch/jobs", params={"cursor": "garbage!!!"})

    assert resp.status_code == 400


def test_list_items_paginates_in_order(client):
    job_id = _submit(client, n_items=3).json()["id"]

    page1 = client.get(f"/v1/batch/jobs/{job_id}/items", params={"limit": 2}).json()
    assert [it["item_index"] for it in page1["items"]] == [0, 1]
    assert page1["items"][0]["input_payload"] == {"prompt": "p0"}
    assert page1["items"][0]["status"] == "queued"
    assert page1["items"][0]["output_payload"] is None
    assert page1["next_cursor"]

    page2 = client.get(
        f"/v1/batch/jobs/{job_id}/items",
        params={"limit": 2, "cursor": page1["next_cursor"]},
    ).json()
    assert [it["item_index"] for it in page2["items"]] == [2]
    assert page2["next_cursor"] is None


def test_list_items_unknown_job_is_404(client):
    resp = client.get(f"/v1/batch/jobs/{uuid.uuid4()}/items")

    assert resp.status_code == 404
