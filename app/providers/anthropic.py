"""Anthropic provider adapter."""
from __future__ import annotations

import time
import uuid
from typing import AsyncIterator

import anthropic

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

_KNOWN_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
]


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        system, messages = _split_messages(request.messages)
        kwargs = _build_kwargs(request)
        resp = await self._client.messages.create(
            model=request.model,
            messages=messages,
            system=system or anthropic.NOT_GIVEN,
            max_tokens=request.max_tokens or 4096,
            **kwargs,
        )
        content = resp.content[0].text if resp.content else ""
        return ChatCompletionResponse(
            id=resp.id,
            model=resp.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason=_map_stop(resp.stop_reason),
                )
            ],
            usage=UsageInfo(
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            ),
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionStreamChunk]:
        system, messages = _split_messages(request.messages)
        kwargs = _build_kwargs(request)
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        async with self._client.messages.stream(
            model=request.model,
            messages=messages,
            system=system or anthropic.NOT_GIVEN,
            max_tokens=request.max_tokens or 4096,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield ChatCompletionStreamChunk(
                    id=chunk_id,
                    model=request.model,
                    choices=[
                        ChatCompletionStreamChoice(
                            index=0,
                            delta=ChatCompletionDelta(content=text),
                            finish_reason=None,
                        )
                    ],
                )
            yield ChatCompletionStreamChunk(
                id=chunk_id,
                model=request.model,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta=ChatCompletionDelta(),
                        finish_reason="stop",
                    )
                ],
            )

    async def list_models(self) -> list[ModelCard]:
        return [ModelCard(id=m, owned_by="anthropic") for m in _KNOWN_MODELS]

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False


def _split_messages(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
    system = ""
    out = []
    for m in messages:
        if m.role == "system":
            system = m.content if isinstance(m.content, str) else ""
        else:
            out.append({"role": m.role, "content": m.content})
    return system, out


def _map_stop(reason: str | None) -> str:
    return {"end_turn": "stop", "max_tokens": "length"}.get(reason or "", "stop")


def _build_kwargs(request: ChatCompletionRequest) -> dict:
    kwargs: dict = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.stop is not None:
        kwargs["stop_sequences"] = [request.stop] if isinstance(request.stop, str) else request.stop
    return kwargs
