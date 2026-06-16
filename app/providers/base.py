"""Abstract base provider."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.schemas.openai_compat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChunk,
    ModelCard,
)


class BaseProvider(ABC):
    name: str = ""

    @abstractmethod
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Non-streaming completion."""

    @abstractmethod
    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionStreamChunk]:
        """Streaming completion — yields chunks."""

    @abstractmethod
    async def list_models(self) -> list[ModelCard]:
        """Return available models for this provider."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable."""
