"""Alembic migration environment.

Reads DATABASE_URL_SYNC from aiinfra.config — Alembic uses the sync driver
(psycopg) while the runtime uses async (asyncpg). Same database, parallel
engines.

Once aiinfra/db/models.py exists (Phase 2), import it here so the table
classes register on SQLModel.metadata for autogenerate to pick up.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import aiinfra.db.models  # noqa: F401  # registers tables on SQLModel.metadata
from aiinfra.config import get_settings

config = context.config

# Override the (empty) URL in alembic.ini with the runtime sync DSN.
config.set_main_option("sqlalchemy.url", get_settings().database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations without a DB connection (emits SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
