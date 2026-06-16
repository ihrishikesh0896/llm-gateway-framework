"""API key authentication — timing-safe."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _is_valid_key(key: str) -> bool:
    """Timing-safe check: key must match at least one configured gateway key."""
    if not settings.gateway_api_keys:
        return True  # auth disabled — all keys accepted (dev mode)
    return any(hmac.compare_digest(key, valid) for valid in settings.gateway_api_keys)


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    key: str | None = None
    if authorization and authorization.startswith("Bearer "):
        key = authorization.removeprefix("Bearer ").strip()
    elif x_api_key:
        key = x_api_key.strip()

    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")

    if not _is_valid_key(key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")

    return key
