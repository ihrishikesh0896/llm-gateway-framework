"""POST /v1/chat/completions — core inference endpoint."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.auth import require_api_key, _hash_key
from app.rate_limit import check_rate_limit, record_tokens
from app.pipeline.pre.prompt_injection import PromptInjectionDetector
from app.pipeline.pre.pii_input import PIIInputDetector
from app.pipeline.pre.secret_detection import SecretDetector
from app.pipeline.pre.policy import PolicyEnforcer, load_policies
from app.pipeline.post.pii_output import PIIOutputScanner
from app.pipeline.scoring import compute_risk_score
from app.providers.router import router as provider_router
from app.schemas.openai_compat import ChatCompletionRequest
from app.config import settings
from app.state import stats

logger = logging.getLogger(__name__)
route = APIRouter()

# Thread/async-safe way to pass the API key into processors without
# attaching it to the Pydantic model (avoids any serialisation risk).
_current_api_key: ContextVar[str] = ContextVar("_current_api_key", default="")

_policies = load_policies(settings.policy_file)

_sync_pre = [
    PolicyEnforcer(policies=_policies),
    PromptInjectionDetector(),
]
_async_pre = [
    SecretDetector(),
    PIIInputDetector(mode=settings.pipeline_pii_mode),
]
_async_post = [
    PIIOutputScanner(mode=settings.pipeline_pii_mode),
]


@route.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request_body: ChatCompletionRequest,
    api_key: Annotated[str, Depends(require_api_key)],
) -> Response:
    start_ts = time.monotonic()
    request_id = str(uuid.uuid4())
    stats.requests_total += 1

    _current_api_key.set(api_key)
    await check_rate_limit(api_key)

    all_findings = []
    for processor in _sync_pre:
        all_findings.extend(processor.scan(request_body))
    for processor in _async_pre:
        all_findings.extend(await processor.async_scan(request_body))

    risk = compute_risk_score(all_findings)

    from app.metrics import gateway_security_events
    for f in all_findings:
        gateway_security_events.labels(code=f.code).inc()
    if any(f.code == "PROMPT_INJECTION_DETECTED" for f in all_findings):
        stats.injection_detections += 1
    if any(f.code in ("PII_DETECTED", "SECRET_DETECTED") for f in all_findings):
        stats.pii_detections += 1

    should_block = (
        any(f.weight >= 100 for f in all_findings)
        or any(f.code == "SECRET_DETECTED" for f in all_findings)
        or (
            settings.pipeline_injection_mode == "block"
            and any(f.code == "PROMPT_INJECTION_DETECTED" for f in all_findings)
        )
        or risk.score >= settings.risk_score_block_threshold
    )

    if should_block:
        stats.requests_blocked += 1
        await _write_audit(
            request_id=request_id,
            api_key=api_key,
            request=request_body,
            provider_name="—",
            blocked=True,
            risk=risk,
            latency_ms=(time.monotonic() - start_ts) * 1000,
        )
        first = all_findings[0] if all_findings else None
        if settings.verbose_errors:
            detail = {
                "code": first.code if first else "REQUEST_BLOCKED",
                "message": first.label if first else "Request blocked by gateway policy",
                "risk_score": risk.score,
                "severity": risk.severity,
                "reasons": risk.reasons,
            }
        else:
            detail = {
                "code": first.code if first else "REQUEST_BLOCKED",
                "message": "Request blocked by gateway policy",
                "severity": risk.severity,
            }
        raise HTTPException(status_code=400, detail=detail)

    headers: dict[str, str] = {
        "x-gateway-risk-score": str(risk.score),
        "x-gateway-risk-severity": risk.severity,
        "x-gateway-request-id": request_id,
    }
    if risk.reasons and settings.verbose_errors:
        headers["x-gateway-risk-reasons"] = ", ".join(risk.reasons)

    provider = provider_router.resolve(request_body.model, request_body.provider)
    provider_name = provider.name

    if request_body.stream:
        headers["x-gateway-stream-mode"] = settings.pipeline_stream_mode
        return StreamingResponse(
            _stream_response(request_body, provider, request_id, api_key, risk, start_ts),
            media_type="text/event-stream",
            headers=headers,
        )

    response = None
    last_exc: Exception | None = None
    for fallback_model in [request_body.model] + provider_router.fallback_chain(request_body.model):
        candidate = provider_router.resolve_by_model_name(fallback_model) if fallback_model != request_body.model else provider
        if candidate is None:
            continue
        try:
            _req = request_body.model_copy(update={"model": fallback_model}) if fallback_model != request_body.model else request_body
            response = await candidate.complete(_req)
            provider_name = candidate.name
            if fallback_model != request_body.model:
                logger.warning("Fell back from %s to %s (request %s)", request_body.model, fallback_model, request_id)
            break
        except Exception as exc:
            logger.warning("Provider %s failed for model %s: %s", candidate.name, fallback_model, exc)
            last_exc = exc

    if response is None:
        logger.error("All providers failed for model %s (request %s): %s", request_body.model, request_id, last_exc)
        raise HTTPException(status_code=502, detail="Upstream provider request failed")

    await record_tokens(api_key, response.usage.total_tokens if response.usage else 0)

    for processor in _async_post:
        response = await processor.async_process(response, request_body)

    pii_out = getattr(response, "_pii_output_warning", [])
    if pii_out:
        headers["x-gateway-pii-output"] = ", ".join(pii_out)
        stats.pii_detections += 1

    await _write_audit(
        request_id=request_id,
        api_key=api_key,
        request=request_body,
        provider_name=provider_name,
        blocked=False,
        risk=risk,
        latency_ms=(time.monotonic() - start_ts) * 1000,
        usage=response.usage,
    )

    return Response(
        content=response.model_dump_json(),
        media_type="application/json",
        headers=headers,
    )


async def _stream_response(request_body, provider, request_id, api_key, risk, start_ts):
    """Stream the LLM response with optional PII output scan.

    pipeline_stream_mode=buffered (default): buffer the full response, run PII
    scan, then re-emit. Safe but adds latency equal to the full generation time.

    pipeline_stream_mode=passthrough: true streaming — chunks are forwarded as
    they arrive. Output PII scan is skipped. Use only when latency matters more
    than output sanitisation.
    """
    if settings.pipeline_stream_mode == "passthrough":
        async for chunk in _stream_passthrough(request_body, provider, request_id, api_key, risk, start_ts):
            yield chunk
        return
    from app.schemas.openai_compat import (
        ChatCompletionResponse, ChatCompletionChoice, ChatMessage,
        ChatCompletionStreamChunk, ChatCompletionStreamChoice, ChatCompletionDelta,
        UsageInfo,
    )

    chunks = []
    full_text = []
    model_used = request_body.model

    try:
        async for chunk in provider.stream(request_body):
            chunks.append(chunk)
            model_used = chunk.model
            for choice in chunk.choices:
                if choice.delta.content:
                    full_text.append(choice.delta.content)
    except Exception as exc:
        logger.error("Stream error (request %s): %s", request_id, exc)
        yield f'data: {json.dumps({"error": {"code": "PROVIDER_ERROR", "message": "Stream failed"}})}\n\n'
        return

    # Estimate token usage from character counts (4 chars ≈ 1 token).
    # Exact counts are unavailable from the streaming API without provider-specific
    # stream options — this approximation is good enough for TPM accounting.
    assembled = "".join(full_text)
    _input_chars = sum(len(m.content) for m in request_body.messages if isinstance(m.content, str))
    _stream_usage = UsageInfo(
        prompt_tokens=max(1, _input_chars // 4),
        completion_tokens=max(1, len(assembled) // 4),
        total_tokens=max(1, (_input_chars + len(assembled)) // 4),
    )
    await record_tokens(api_key, _stream_usage.total_tokens)

    if assembled and settings.pipeline_pii_mode != "off":
        synthetic_response = ChatCompletionResponse(
            model=model_used,
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content=assembled),
                finish_reason="stop",
            )],
        )
        for processor in _async_post:
            synthetic_response = await processor.async_process(synthetic_response, request_body)
        cleaned_text = synthetic_response.choices[0].message.content
        if cleaned_text != assembled:
            # Emit as a single replacement chunk instead of the original buffered chunks
            import uuid as _uuid
            chunk_id = f"chatcmpl-{_uuid.uuid4().hex}"
            yield f'data: {ChatCompletionStreamChunk(id=chunk_id, model=model_used, choices=[ChatCompletionStreamChoice(index=0, delta=ChatCompletionDelta(role="assistant", content=cleaned_text), finish_reason=None)]).model_dump_json()}\n\n'
            yield f'data: {ChatCompletionStreamChunk(id=chunk_id, model=model_used, choices=[ChatCompletionStreamChoice(index=0, delta=ChatCompletionDelta(), finish_reason="stop")]).model_dump_json()}\n\n'
            yield "data: [DONE]\n\n"
            await _write_audit(request_id=request_id, api_key=api_key, request=request_body, provider_name=provider.name, blocked=False, risk=risk, latency_ms=(time.monotonic() - start_ts) * 1000, usage=_stream_usage)
            return

    # No PII found or PII mode off — re-stream original chunks
    for chunk in chunks:
        yield f"data: {chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"

    await _write_audit(
        request_id=request_id, api_key=api_key, request=request_body,
        provider_name=provider.name, blocked=False, risk=risk,
        latency_ms=(time.monotonic() - start_ts) * 1000,
        usage=_stream_usage,
    )


async def _stream_passthrough(request_body, provider, request_id, api_key, risk, start_ts):
    """True passthrough streaming — no output buffering, no PII output scan."""
    try:
        async for chunk in provider.stream(request_body):
            yield f"data: {chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.error("Passthrough stream error (request %s): %s", request_id, exc)
        yield f'data: {{"error": {{"code": "PROVIDER_ERROR", "message": "Stream failed"}}}}\n\n'
        return
    await _write_audit(
        request_id=request_id, api_key=api_key, request=request_body,
        provider_name=provider.name, blocked=False, risk=risk,
        latency_ms=(time.monotonic() - start_ts) * 1000,
    )


async def _write_audit(*, request_id, api_key, request, provider_name, blocked, risk, latency_ms, usage=None):
    try:
        from app.db import write_audit_log, _compute_cost
        from app.metrics import gateway_requests, gateway_tokens, gateway_latency, gateway_cost, gateway_security_events
        status = "blocked" if blocked else "success"
        gateway_requests.labels(model=request.model, provider=provider_name, status=status).inc()
        gateway_latency.labels(model=request.model, provider=provider_name).observe(latency_ms / 1000)
        if usage:
            gateway_tokens.labels(model=request.model, token_type="input").inc(usage.prompt_tokens)
            gateway_tokens.labels(model=request.model, token_type="output").inc(usage.completion_tokens)
            cost = _compute_cost(request.model, usage.prompt_tokens, usage.completion_tokens)
            gateway_cost.labels(model=request.model).inc(cost)
        await write_audit_log(
            request_id=request_id,
            api_key_hash=_hash_key(api_key),
            model=request.model,
            provider=provider_name,
            blocked=blocked,
            risk_score=risk.score,
            severity=risk.severity,
            reasons=risk.reasons,
            latency_ms=latency_ms,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
    except Exception as exc:
        logger.warning("Audit log write failed: %s", exc)
