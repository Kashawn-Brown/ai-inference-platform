"""Batch job API schemas (brief Section 3).

Request shapes for submitting jobs and response shapes for reading jobs and
items. These are the API surface — distinct from the SQLModel tables in
`db/models.py`. Read models set `from_attributes=True` so they validate
straight from ORM rows.

The submit request carries an optional `model`: when omitted the gateway
stamps the job's `model_name` from the active `model_configs` row; when present
it is validated against an existing config. The gateway never serves the model
here — it only records jobs/items as `queued` for the worker to process.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BatchJobItemCreate(BaseModel):
    input_payload: dict = Field(description="Per-item input, e.g. {'prompt': '...'}.")


class BatchJobCreate(BaseModel):
    name: str = Field(min_length=1)
    # Optional: omitted -> resolved from the active model_configs row.
    model: str | None = Field(default=None)
    # Loose operational identifier (e.g. "benchmark-runner"), not a tenant.
    submitted_by: str | None = Field(default=None)
    job_type: str = Field(default="inference")
    items: list[BatchJobItemCreate] = Field(min_length=1)


class BatchJobRead(BaseModel):
    # protected_namespaces=() — `model_name` would otherwise warn about the
    # reserved `model_` prefix.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    name: str
    submitted_by: str | None
    model_name: str
    job_type: str
    input_source: str | None
    status: str
    total_items: int
    completed_items: int
    failed_items: int
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime | None


class BatchJobItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_job_id: uuid.UUID
    item_index: int
    input_payload: dict
    output_payload: dict | None
    status: str
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None


class BatchJobList(BaseModel):
    jobs: list[BatchJobRead]
    # Opaque token to fetch the next page; null when there are no more rows.
    next_cursor: str | None = None


class BatchJobItemList(BaseModel):
    items: list[BatchJobItemRead]
    next_cursor: str | None = None
