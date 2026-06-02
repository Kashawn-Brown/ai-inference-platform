"""Model-config API schema (brief Section 3, read-only in v1).

`model_configs` is the source of truth for which model the platform serves and
with what serving parameters. `/v1/models` exposes it read-only: the list view
filters to active configs, the detail view returns whatever exists by name.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ModelConfigRead(BaseModel):
    # protected_namespaces=() — `model_name` would otherwise warn about the
    # reserved `model_` prefix.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    model_name: str
    provider_type: str
    serving_mode: str
    max_tokens_default: int
    timeout_ms: int
    concurrency_limit: int | None
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None
