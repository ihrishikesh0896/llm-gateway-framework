"""Per-API-key rate limiter backed by SQLite (tumbling minute window).

Flow:
  1. check_rate_limit(api_key)   — called BEFORE the LLM request.
     Increments the request counter and enforces RPM.
     TPM is enforced against tokens accumulated by previous requests this window.

  2. record_tokens(api_key, n)   — called AFTER the LLM response.
     Adds actual token usage so the next request's TPM check is accurate.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.auth import _hash_key
from app.config import settings
from app.db import add_token_count, increment_request_count


async def check_rate_limit(api_key: str) -> None:
    """Gate the request: increment request counter and enforce RPM/TPM limits."""
    key_hash = _hash_key(api_key)
    req_count, token_count = await increment_request_count(key_hash)

    if settings.rate_limit_rpm and req_count > settings.rate_limit_rpm:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Request rate limit exceeded ({settings.rate_limit_rpm} RPM)",
            },
            headers={"Retry-After": "60"},
        )

    if settings.rate_limit_tpm and token_count > settings.rate_limit_tpm:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "TOKEN_LIMIT_EXCEEDED",
                "message": f"Token rate limit exceeded ({settings.rate_limit_tpm} TPM)",
            },
            headers={"Retry-After": "60"},
        )


async def record_tokens(api_key: str, tokens: int) -> None:
    """Record actual token usage after a completed request.
    Updates the current window's token total so subsequent requests see accurate counts."""
    if tokens > 0:
        await add_token_count(_hash_key(api_key), tokens)
