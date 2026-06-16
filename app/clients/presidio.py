"""HTTP client for Microsoft Presidio analyzer and anonymizer sidecars."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)

_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
    "US_SSN", "IBAN_CODE", "IP_ADDRESS", "LOCATION", "URL",
    "US_BANK_NUMBER", "US_PASSPORT", "MEDICAL_LICENSE",
]

_MIN_SCORE = 0.6


async def analyze(text: str) -> list[dict[str, Any]]:
    """Call presidio-analyzer. Returns list of RecognizerResult dicts.
    Returns [] on network error (graceful degradation)."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.presidio_analyzer_url}/analyze",
                json={"text": text, "language": "en", "entities": _ENTITIES, "score_threshold": _MIN_SCORE},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        if settings.sidecar_fail_closed:
            logger.error("Presidio analyzer unreachable (fail-closed): %s", exc)
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail="PII scanning service unavailable")
        logger.warning("Presidio analyzer unreachable (fail-open, PII scanning skipped): %s", exc)
        return []


async def anonymize(text: str, analyzer_results: list[dict]) -> str:
    """Call presidio-anonymizer. Returns redacted text.
    Returns original text on network error."""
    if not analyzer_results:
        return text

    operators = {
        r["entity_type"]: {"type": "replace", "new_value": f"[{r['entity_type']}_REDACTED]"}
        for r in analyzer_results
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.presidio_anonymizer_url}/anonymize",
                json={"text": text, "anonymizers": operators, "analyzer_results": analyzer_results},
            )
            resp.raise_for_status()
            return resp.json().get("text", text)
    except Exception as exc:
        logger.warning("Presidio anonymizer unreachable: %s", exc)
        return text


async def detect_and_redact(text: str, mode: str) -> tuple[str, list[str]]:
    """Convenience: analyze then optionally anonymize. Returns (text, detected_types)."""
    results = await analyze(text)
    if not results:
        return text, []

    detected = list({r["entity_type"] for r in results})

    if mode == "flag":
        return text, detected

    redacted = await anonymize(text, results)
    return redacted, detected
