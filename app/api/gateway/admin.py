"""Gateway admin endpoints — stats and audit log."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_api_key
from app.schemas.gateway import StatsResponse
from app.state import stats

route = APIRouter()


@route.get("/gateway/stats", response_model=StatsResponse)
async def get_stats(_key: Annotated[str, Depends(require_api_key)]) -> StatsResponse:
    return StatsResponse(
        requests_total=stats.requests_total,
        requests_blocked=stats.requests_blocked,
        pii_detections=stats.pii_detections,
        injection_detections=stats.injection_detections,
    )


@route.get("/gateway/audit")
async def get_audit_log(
    _key: Annotated[str, Depends(require_api_key)],
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    from app.db import get_audit_logs
    rows = await get_audit_logs(limit=limit, offset=offset)
    return {"total": len(rows), "offset": offset, "limit": limit, "data": rows}
