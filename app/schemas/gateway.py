"""Extended gateway-specific schemas."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel


class ProviderStatus(BaseModel):
    name: str
    available: bool
    models: list[str] = []
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    providers: list[ProviderStatus]


class StatsResponse(BaseModel):
    requests_total: int
    requests_blocked: int
    pii_detections: int
    injection_detections: int


class GatewayError(BaseModel):
    error: dict[str, Any]

    @classmethod
    def make(cls, code: str, message: str, status: int = 400) -> "GatewayError":
        return cls(error={"code": code, "message": message, "status": status})
