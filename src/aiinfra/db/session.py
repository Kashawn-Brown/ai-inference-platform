"""Async session helpers.

`get_session` is the FastAPI dependency that yields a per-request
AsyncSession. The session factory is a lazy singleton built on top of
the engine factory in `engine.py`.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aiinfra.db.engine import get_engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
