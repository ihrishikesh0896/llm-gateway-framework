"""GET /v1/models — aggregated model list."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_api_key
from app.providers.router import router as provider_router
from app.schemas.openai_compat import ModelList

route = APIRouter()


@route.get("/v1/models", response_model=ModelList)
async def list_models(_key: Annotated[str, Depends(require_api_key)]) -> ModelList:
    all_models = []
    for provider in provider_router.all_providers().values():
        try:
            models = await provider.list_models()
            all_models.extend(models)
        except Exception:
            pass
    return ModelList(data=all_models)
