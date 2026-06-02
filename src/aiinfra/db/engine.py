"""Async SQLAlchemy engine factory.

Lazy singleton — the engine is constructed on first call so process start
doesn't fail when the DB isn't reachable yet (e.g. /healthz before
postgres comes up). Alembic uses a parallel sync engine; same DB, different
driver.
"""

import logging
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aiinfra.config import get_settings

logger = logging.getLogger("aiinfra.db.engine")


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, future=True)


async def check_database() -> bool:
    """Readiness probe — True if a trivial query succeeds.

    SQLAlchemy wraps connection failures (refused, DNS, auth) as
    SQLAlchemyError, so that's the boundary we treat as "not ready".
    """
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("database readiness check failed", extra={"error": str(exc)})
        return False
    return True
