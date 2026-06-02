"""SQLModel table models for the batch subsystem (brief Section 4).

Three tables back Phase 2: `batch_jobs`, `batch_job_items`, and
`model_configs`. Live-inference data is deliberately NOT here — it lives in
logs and metrics (brief Section 4 / Section 5).

Model-resolution contract: the authoritative answer to "which model do we
serve?" is the active `model_configs` row (`is_active = true`), NOT the
`VLLM_MODEL_NAME` env var. The worker reads serving identity and parameters
(timeout, default max tokens) from this table. Config/env seeds the row once
via migration; from then on the DB is the source of truth.

The server-stamped timestamps (`created_at`/`updated_at`) carry a
`server_default` of now(), so the DB fills them on insert — the Python
attribute stays None until the row is flushed and refreshed.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class JobStatus(StrEnum):
    """Lifecycle of a batch job. Stored as text (brief Section 4)."""

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ItemStatus(StrEnum):
    """Lifecycle of a single item within a job. Stored as text."""

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"


class BatchJob(SQLModel, table=True):
    __tablename__ = "batch_jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    # Loose operational identifier (e.g. "benchmark-runner", "dev-cli") —
    # NOT a user/tenant system (brief Section 4).
    submitted_by: str | None = Field(default=None)
    # Logical reference to model_configs.model_name (not a strict FK).
    model_name: str
    job_type: str
    # URI/ref for external input, or NULL when items are inline.
    input_source: str | None = Field(default=None)
    status: str = Field(default=JobStatus.QUEUED.value)
    total_items: int
    completed_items: int = Field(default=0)
    failed_items: int = Field(default=0)
    created_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
    started_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    completed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
        nullable=False,
    )


class BatchJobItem(SQLModel, table=True):
    __tablename__ = "batch_job_items"
    # Composite index serves the worker claim query
    # (WHERE batch_job_id = ? AND status = 'queued').
    __table_args__ = (Index("ix_batch_job_items_job_status", "batch_job_id", "status"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    batch_job_id: uuid.UUID = Field(foreign_key="batch_jobs.id")
    item_index: int  # order within the job
    input_payload: dict = Field(sa_type=JSONB)
    output_payload: dict | None = Field(default=None, sa_type=JSONB, nullable=True)
    status: str = Field(default=ItemStatus.QUEUED.value)
    error_message: str | None = Field(default=None)
    created_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
        nullable=False,
    )


class ModelConfig(SQLModel, table=True):
    __tablename__ = "model_configs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    model_name: str = Field(unique=True, index=True)
    provider_type: str  # "vllm" in v1
    serving_mode: str  # "local" in v1
    max_tokens_default: int
    timeout_ms: int
    concurrency_limit: int | None = Field(default=None)
    # The worker resolves the served model from the active row, not from env.
    is_active: bool
    created_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
        nullable=False,
    )
