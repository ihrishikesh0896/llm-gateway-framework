"""LLM06 – PII detection on request input via Presidio sidecar."""
from __future__ import annotations

from app.clients import presidio
from app.pipeline.base import Finding, PreProcessor
from app.schemas.openai_compat import ChatCompletionRequest


class PIIInputDetector(PreProcessor):
    def __init__(self, mode: str = "redact") -> None:
        self.mode = mode  # "redact" | "flag" | "off"

    def scan(self, request: ChatCompletionRequest) -> list[Finding]:
        # scan() is sync by contract; async work is dispatched in the route.
        # Use the async helper via the route-level wrapper instead.
        raise NotImplementedError("Use async_scan()")

    async def async_scan(self, request: ChatCompletionRequest) -> list[Finding]:
        if self.mode == "off":
            return []

        findings: list[Finding] = []
        for msg in request.messages:
            if not isinstance(msg.content, str) or not msg.content:
                continue
            new_text, detected = await presidio.detect_and_redact(msg.content, self.mode)
            if detected:
                if self.mode == "redact":
                    msg.content = new_text
                for entity in detected:
                    findings.append(Finding(
                        code="PII_DETECTED",
                        label=f"PII in input: {entity}",
                        weight=15,
                        detail=entity,
                    ))
        return findings
