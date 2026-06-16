"""Prometheus custom metrics."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

gateway_requests = Counter(
    "gateway_requests_total",
    "Total requests processed",
    ["model", "provider", "status"],   # status: success | blocked | error
)

gateway_tokens = Counter(
    "gateway_tokens_total",
    "Total tokens processed",
    ["model", "token_type"],            # token_type: input | output
)

gateway_security_events = Counter(
    "gateway_security_events_total",
    "Security events detected",
    ["code"],                           # PROMPT_INJECTION_DETECTED, SECRET_DETECTED, etc.
)

gateway_latency = Histogram(
    "gateway_request_duration_seconds",
    "End-to-end request latency",
    ["model", "provider"],
    buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
)

gateway_cost = Counter(
    "gateway_cost_usd_total",
    "Estimated token cost in USD",
    ["model"],
)
