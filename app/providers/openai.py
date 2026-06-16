"""OpenAI provider adapter."""
from __future__ import annotations

import time
import uuid
from typing import AsyncIterator

import openai

from app.providers.base import BaseProvider
from app.schemas.openai_compat import (
    ChatCompletionChoice,
    ChatCompletionDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChoice,
    ChatCompletionStreamChunk,
    ChatMessage,
    ModelCard,
    UsageInfo,
)


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, api_key: str) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        kwargs = _build_kwargs(request)
        resp = await self._client.chat.completions.create(
            model=request.model, messages=messages, stream=False, **kwargs
        )
        return ChatCompletionResponse(
            id=resp.id,
            model=resp.model,
            choices=[
                ChatCompletionChoice(
                    index=c.index,
                    message=ChatMessage(role=c.message.role, content=c.message.content or ""),
                    finish_reason=c.finish_reason,
                )
                for c in resp.choices
            ],
            usage=UsageInfo(
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
                total_tokens=resp.usage.total_tokens if resp.usage else 0,
            ),
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionStreamChunk]:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        kwargs = _build_kwargs(request)
        async with self._client.chat.completions.stream(
            model=request.model, messages=messages, **kwargs
        ) as stream:
            async for chunk in stream:
                yield ChatCompletionStreamChunk(
                    id=chunk.id,
                    model=chunk.model,
                    choices=[
                        ChatCompletionStreamChoice(
                            index=c.index,
                            delta=ChatCompletionDelta(
                                role=c.delta.role,
                                content=c.delta.content,
                            ),
                            finish_reason=c.finish_reason,
                        )
                        for c in chunk.choices
                    ],
                )

    async def list_models(self) -> list[ModelCard]:
        models = await self._client.models.list()
        return [ModelCard(id=m.id, owned_by=m.owned_by) for m in models.data]

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False


def _build_kwargs(request: ChatCompletionRequest) -> dict:
    kwargs: dict = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.stop is not None:
        kwargs["stop"] = request.stop
    if request.presence_penalty is not None:
        kwargs["presence_penalty"] = request.presence_penalty
    if request.frequency_penalty is not None:
        kwargs["frequency_penalty"] = request.frequency_penalty
    return kwargs
