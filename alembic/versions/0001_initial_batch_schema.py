"""initial batch schema: batch_jobs, batch_job_items, model_configs

Creates the Phase 2 batch tables (brief Section 4) and seeds the single
active model config so the batch path has a real model to resolve against
from day one. The seed is hardcoded rather than read from env: the migration
must be deterministic, and model_configs is the source of truth the worker
queries — not VLLM_MODEL_NAME.

Revision ID: 0001_initial_batch_schema
Revises:
Create Date: 2026-06-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_batch_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("model_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("serving_mode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("max_tokens_default", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_configs_model_name"),
        "model_configs",
        ["model_name"],
        unique=True,
    )

    op.create_table(
        "batch_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("submitted_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("model_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("job_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("input_source", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "batch_job_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("batch_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["batch_job_id"], ["batch_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_batch_job_items_job_status",
        "batch_job_items",
        ["batch_job_id", "status"],
    )

    # Seed the single active model config. Values mirror the v1 config
    # defaults (Qwen2.5-1.5B-Instruct, 30s timeout, 512 default tokens);
    # the DB owns them from here on. id/timestamps come from server defaults.
    op.execute(sa.text("""
            INSERT INTO model_configs
                (model_name, provider_type, serving_mode,
                 max_tokens_default, timeout_ms, concurrency_limit, is_active)
            VALUES
                ('Qwen/Qwen2.5-1.5B-Instruct', 'vllm', 'local',
                 512, 30000, NULL, true)
            """))


def downgrade() -> None:
    op.drop_index("ix_batch_job_items_job_status", table_name="batch_job_items")
    op.drop_table("batch_job_items")
    op.drop_table("batch_jobs")
    op.drop_index(op.f("ix_model_configs_model_name"), table_name="model_configs")
    op.drop_table("model_configs")
