"""Secret detection pre-processor via the gitleaks sidecar."""
from __future__ import annotations

from app.clients import gitleaks
from app.pipeline.base import Finding, PreProcessor
from app.schemas.openai_compat import ChatCompletionRequest


class SecretDetector(PreProcessor):
    def scan(self, request: ChatCompletionRequest) -> list[Finding]:
        raise NotImplementedError("Use async_scan()")

    async def async_scan(self, request: ChatCompletionRequest) -> list[Finding]:
        text = _extract_text(request)
        if not text.strip():
            return []

        hits = await gitleaks.scan(text)
        return [
            Finding(
                code="SECRET_DETECTED",
                label=f"Secret detected: {h['description']}",
                weight=h.get("weight", 40),
                detail=h["rule_id"],
            )
            for h in hits
        ]


def _extract_text(request: ChatCompletionRequest) -> str:
    parts = []
    for msg in request.messages:
        if isinstance(msg.content, str):
            parts.append(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)
