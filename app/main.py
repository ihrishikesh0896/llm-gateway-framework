"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.chat import route as chat_route
from app.api.v1.models import route as models_route
from app.api.gateway.health import route as health_route
from app.api.gateway.admin import route as admin_route
from app.config import settings


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > settings.max_request_body_bytes:
                return Response(
                    content='{"detail": "Request body too large"}',
                    status_code=413,
                    media_type="application/json",
                )
        return await call_next(request)


def _validate_production_config() -> None:
    """Refuse to start if unsafe settings are used in production."""
    if settings.gateway_env != "production":
        return
    errors: list[str] = []
    if not settings.gateway_api_keys:
        errors.append("GATEWAY_API_KEYS must be set — unauthenticated mode is not allowed")
    if not settings.sidecar_fail_closed:
        errors.append("SIDECAR_FAIL_CLOSED must be true — fail-open sidecars are not allowed")
    if settings.verbose_errors:
        errors.append("VERBOSE_ERRORS must be false — exposing internals to callers is not allowed")
    if settings.pipeline_pii_mode == "off":
        errors.append("PIPELINE_PII_MODE cannot be 'off'")
    if settings.pipeline_injection_mode != "block":
        errors.append("PIPELINE_INJECTION_MODE must be 'block'")
    if errors:
        raise RuntimeError(
            "Production startup validation failed:\n" +
            "\n".join(f"  ✗ {e}" for e in errors)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db import init_db
    _validate_production_config()
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI API Gateway",
        description="Open-source AI API Gateway with multi-provider routing and OWASP LLM security guardrails.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(MaxBodySizeMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins or [],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
        allow_credentials=False,
        max_age=3600,
    )

    app.include_router(chat_route)
    app.include_router(models_route)
    app.include_router(health_route)
    app.include_router(admin_route)

    from prometheus_client import make_asgi_app
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    return app


app = create_app()
