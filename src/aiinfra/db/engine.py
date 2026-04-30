"""Async SQLAlchemy engine factory.

Lazy singleton — the engine is constructed on first call so process start
doesn't fail when the DB isn't reachable yet (e.g. /healthz before
postgres comes up). Alembic uses a parallel sync engine; same DB, different
driver.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aiinfra.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, future=True)
