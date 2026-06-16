"""Pipeline base classes, Finding dataclass, and security exception."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.schemas.openai_compat import ChatCompletionRequest, ChatCompletionResponse


@dataclass
class Finding:
    code: str        # e.g. "PROMPT_INJECTION", "SECRET_DETECTED", "PII_DETECTED"
    label: str       # human-readable reason shown in risk response
    weight: int      # contribution to risk score (0-100)
    detail: str = "" # specific match info (rule id, entity type, etc.)


class SecurityException(Exception):
    """Raised by process() legacy path. Prefer scan() + risk scoring."""
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class PreProcessor(ABC):
    @abstractmethod
    def scan(self, request: ChatCompletionRequest) -> list[Finding]:
        """Scan the request and return findings. Never raises."""

    def process(self, request: ChatCompletionRequest) -> None:
        """Legacy blocking path — raises on any finding."""
        findings = self.scan(request)
        if findings:
            raise SecurityException(code=findings[0].code, detail=findings[0].label)


class PostProcessor(ABC):
    @abstractmethod
    def process(self, response: ChatCompletionResponse, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Mutate or replace the response. Return the (possibly modified) response."""
