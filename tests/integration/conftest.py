"""Integration test fixtures for the DB-backed endpoints.

Provides a `client` fixture (FastAPI TestClient with the DB session overridden
to a dedicated test database) and the supporting schema/seed/cleanup fixtures.

These are intentionally NOT autouse: only tests that request `client` spin up
the test DB, so the DB-free Phase 1 integration tests stay independent of
Postgres. The test database is separate (`aiinfra_test` by default) so runs
never touch dev data; schema is created via SQLModel metadata and the batch
tables are truncated before each test.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

import aiinfra.db.models  # noqa: F401  # register tables on SQLModel.metadata
from aiinfra.config import get_settings
from aiinfra.db.session import get_session
from aiinfra.gateway.main import create_app

# Seeded model configs the endpoint tests assert against.
ACTIVE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
INACTIVE_MODEL = "legacy/old-model"


def _sync_url(async_url: str, database: str | None = None):
    """Same DSN as `async_url` but with the sync psycopg driver (and optionally
    a different database — used to reach the always-present 'postgres' DB)."""
    url = make_url(async_url).set(drivername="postgresql+psycopg")
    if database is not None:
        url = url.set(database=database)
    return url


@pytest.fixture(scope="session")
def _sync_test_engine():
    async_url = get_settings().test_database_url
    dbname = make_url(async_url).database

    # Create the test database if it doesn't exist (CREATE DATABASE can't run
    # inside a transaction, hence AUTOCOMMIT on the maintenance connection).
    maint = create_engine(
        _sync_url(async_url, "postgres"), isolation_level="AUTOCOMMIT"
    )
    with maint.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    maint.dispose()

    engine = create_engine(_sync_url(async_url))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _schema(_sync_test_engine):
    SQLModel.metadata.create_all(_sync_test_engine)
    with _sync_test_engine.begin() as conn:
        conn.execute(text("DELETE FROM model_configs"))
        # id via gen_random_uuid(): create_all builds the table from the model,
        # whose id default is Python-side (uuid4), so the test schema has no
        # server default like the migration does.
        conn.execute(
            text(
                "INSERT INTO model_configs "
                "(id, model_name, provider_type, serving_mode, "
                " max_tokens_default, timeout_ms, is_active) "
                "VALUES (gen_random_uuid(), :active, 'vllm', 'local', "
                "        512, 30000, true), "
                "       (gen_random_uuid(), :inactive, 'vllm', 'local', "
                "        512, 30000, false)"
            ),
            {"active": ACTIVE_MODEL, "inactive": INACTIVE_MODEL},
        )
    yield


@pytest.fixture
def _clean_batch_tables(_sync_test_engine, _schema):
    # Reset batch state before each test; the seeded model_configs persist.
    with _sync_test_engine.begin() as conn:
        conn.execute(
            text("TRUNCATE batch_job_items, batch_jobs RESTART IDENTITY CASCADE")
        )
    yield


@pytest.fixture
def session_factory(_clean_batch_tables):
    """Async session factory against the test DB, for code that takes a session
    directly (e.g. the worker claim layer) rather than going through the API.

    NullPool so each session opens/closes its own connection in the running
    event loop; expire_on_commit=False so claimed rows stay usable post-commit.
    """
    engine = create_async_engine(get_settings().test_database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    asyncio.run(engine.dispose())


@pytest.fixture
def client(_clean_batch_tables):
    # NullPool: each request opens/closes its own connection in the TestClient's
    # event loop, so no asyncpg connection is reused across loops.
    engine = create_async_engine(get_settings().test_database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())
