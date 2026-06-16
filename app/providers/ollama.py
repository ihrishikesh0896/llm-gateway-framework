"""Ollama (local model) provider adapter."""
from __future__ import annotations

import uuid
from typing import AsyncIterator

import httpx

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


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload = _build_payload(request, stream=False)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("message", {}).get("content", "")
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionStreamChunk]:
        payload = _build_payload(request, stream=True)
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    import json
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    done = data.get("done", False)
                    yield ChatCompletionStreamChunk(
                        id=chunk_id,
                        model=request.model,
                        choices=[
                            ChatCompletionStreamChoice(
                                index=0,
                                delta=ChatCompletionDelta(content=content if not done else None),
                                finish_reason="stop" if done else None,
                            )
                        ],
                    )

    async def list_models(self) -> list[ModelCard]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [ModelCard(id=m["name"], owned_by="ollama") for m in data.get("models", [])]
        except Exception:
            return []

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False


def _build_payload(request: ChatCompletionRequest, stream: bool) -> dict:
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    payload: dict = {"model": request.model, "messages": messages, "stream": stream}
    options: dict = {}
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.top_p is not None:
        options["top_p"] = request.top_p
    if request.max_tokens is not None:
        options["num_predict"] = request.max_tokens
    if options:
        payload["options"] = options
    return payload
