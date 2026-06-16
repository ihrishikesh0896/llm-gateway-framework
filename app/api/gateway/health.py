"""GET /gateway/health — per-provider health status."""
from __future__ import annotations

from fastapi import APIRouter

from app.providers.router import router as provider_router
from app.schemas.gateway import HealthResponse, ProviderStatus

route = APIRouter()


@route.get("/gateway/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    statuses = []
    for name, provider in provider_router.all_providers().items():
        try:
            ok = await provider.health_check()
            models = [m.id for m in await provider.list_models()] if ok else []
            statuses.append(ProviderStatus(name=name, available=ok, models=models))
        except Exception as exc:
            statuses.append(ProviderStatus(name=name, available=False, error=str(exc)))

    overall = "ok" if all(s.available for s in statuses) else "degraded"
    return HealthResponse(status=overall, providers=statuses)
