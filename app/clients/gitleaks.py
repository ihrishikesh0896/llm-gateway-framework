"""HTTP client for the gitleaks sidecar service."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(15.0)


async def scan(text: str) -> list[dict[str, Any]]:
    """Call the gitleaks sidecar. Returns list of finding dicts.
    Fail-closed or fail-open depending on SIDECAR_FAIL_CLOSED setting."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.gitleaks_sidecar_url}/scan",
                json={"text": text},
            )
            resp.raise_for_status()
            return resp.json().get("findings", [])
    except Exception as exc:
        if settings.sidecar_fail_closed:
            logger.error("Gitleaks sidecar unreachable (fail-closed): %s", exc)
            raise HTTPException(status_code=503, detail="Secret scanning service unavailable")
        logger.warning("Gitleaks sidecar unreachable (fail-open, scanning skipped): %s", exc)
        return []
