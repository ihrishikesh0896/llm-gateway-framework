"""LLM06 – PII detection on provider response output via Presidio sidecar."""
from __future__ import annotations

from app.clients import presidio
from app.pipeline.base import PostProcessor
from app.schemas.openai_compat import ChatCompletionRequest, ChatCompletionResponse


class PIIOutputScanner(PostProcessor):
    def __init__(self, mode: str = "redact") -> None:
        self.mode = mode  # "redact" | "flag" | "off"

    def process(self, response: ChatCompletionResponse, request: ChatCompletionRequest) -> ChatCompletionResponse:
        raise NotImplementedError("Use async_process()")

    async def async_process(
        self, response: ChatCompletionResponse, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        if self.mode == "off":
            return response

        for choice in response.choices:
            text = choice.message.content
            if not isinstance(text, str) or not text:
                continue
            new_text, detected = await presidio.detect_and_redact(text, self.mode)
            if detected:
                if self.mode == "redact":
                    choice.message.content = new_text
                existing = getattr(response, "_pii_output_warning", [])
                response._pii_output_warning = existing + detected  # type: ignore[attr-defined]

        return response
