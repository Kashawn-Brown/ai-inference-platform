"""Model-config endpoints (brief Section 3, read-only in v1).

`GET /v1/models` lists active configs; `GET /v1/models/{name}` returns one by
name (active or not). Read-only — `model_configs` is seeded/managed via
migration, not the API.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiinfra.db.models import ModelConfig
from aiinfra.db.session import get_session
from aiinfra.schemas.model_config import ModelConfigRead

router = APIRouter(tags=["models"])


@router.get("/v1/models", response_model=list[ModelConfigRead])
async def list_models(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ModelConfigRead]:
    stmt = (
        select(ModelConfig)
        .where(ModelConfig.is_active.is_(True))
        .order_by(ModelConfig.model_name.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [ModelConfigRead.model_validate(config) for config in rows]


# {name:path} because model names contain slashes (e.g. "Qwen/Qwen2.5-...").
@router.get("/v1/models/{name:path}", response_model=ModelConfigRead)
async def get_model(
    name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ModelConfigRead:
    stmt = select(ModelConfig).where(ModelConfig.model_name == name).limit(1)
    config = (await session.execute(stmt)).scalars().first()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Model not found."
        )
    return ModelConfigRead.model_validate(config)
