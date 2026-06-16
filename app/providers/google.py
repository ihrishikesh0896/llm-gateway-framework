"""Google Gemini provider adapter (google-genai SDK)."""
from __future__ import annotations

import uuid
from typing import AsyncIterator

from google import genai
from google.genai import types

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
    "gemini-2.0-flash-exp",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]


class GoogleProvider(BaseProvider):
    name = "google"

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        contents, config = _build_request(request)
        resp = await self._client.aio.models.generate_content(
            model=request.model,
            contents=contents,
            config=config,
        )
        text = resp.text or ""
        usage = resp.usage_metadata
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=text),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=usage.prompt_token_count if usage else 0,
                completion_tokens=usage.candidates_token_count if usage else 0,
                total_tokens=usage.total_token_count if usage else 0,
            ),
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionStreamChunk]:
        contents, config = _build_request(request)
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        async for chunk in await self._client.aio.models.generate_content_stream(
            model=request.model,
            contents=contents,
            config=config,
        ):
            text = chunk.text or ""
            if text:
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
        return [ModelCard(id=m, owned_by="google") for m in _KNOWN_MODELS]

    async def health_check(self) -> bool:
        try:
            async for _ in self._client.aio.models.list():
                return True
            return True
        except Exception:
            return False


def _build_request(request: ChatCompletionRequest) -> tuple[list, types.GenerateContentConfig]:
    contents = []
    system_instruction = None
    for m in request.messages:
        if m.role == "system":
            system_instruction = m.content if isinstance(m.content, str) else str(m.content)
        else:
            role = "model" if m.role == "assistant" else "user"
            text = m.content if isinstance(m.content, str) else str(m.content)
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    cfg: dict = {}
    if system_instruction:
        cfg["system_instruction"] = system_instruction
    if request.temperature is not None:
        cfg["temperature"] = request.temperature
    if request.top_p is not None:
        cfg["top_p"] = request.top_p
    if request.max_tokens is not None:
        cfg["max_output_tokens"] = request.max_tokens
    if request.stop is not None:
        cfg["stop_sequences"] = [request.stop] if isinstance(request.stop, str) else request.stop

    return contents, types.GenerateContentConfig(**cfg)
