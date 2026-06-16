"""LLM01 – Prompt Injection detection pre-processor."""
from __future__ import annotations

import re

from app.pipeline.base import Finding, PreProcessor
from app.schemas.openai_compat import ChatCompletionRequest

_PATTERNS: list[tuple[re.Pattern, int]] = [  # (pattern, weight)
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context)", re.I), 40),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I), 40),
    (re.compile(r"forget\s+(everything|all)\s+(you('ve)?\s+been\s+told|above)", re.I), 35),
    (re.compile(r"you\s+are\s+now\s+(a|an)\s+\w+\s+(without|that\s+(ignores?|has\s+no))", re.I), 35),
    (re.compile(r"\bdo\s+anything\s+now\b", re.I), 40),  # DAN
    (re.compile(r"\bjailbreak\b", re.I), 35),
    (re.compile(r"override\s+(your\s+)?(system\s+)?(prompt|instructions?|programming)", re.I), 40),
    (re.compile(r"system\s+prompt\s*:", re.I), 30),
    (re.compile(r"act\s+as\s+if\s+(you\s+have\s+no|there\s+are\s+no)\s+(restrictions?|limits?|rules?)", re.I), 35),
    (re.compile(r"\[\s*INST\s*\].*override", re.I | re.DOTALL), 40),
]


class PromptInjectionDetector(PreProcessor):
    def scan(self, request: ChatCompletionRequest) -> list[Finding]:
        text = _extract_text(request)
        findings: list[Finding] = []
        seen_weights: set[int] = set()

        for pattern, weight in _PATTERNS:
            if pattern.search(text) and weight not in seen_weights:
                seen_weights.add(weight)
                findings.append(
                    Finding(
                        code="PROMPT_INJECTION_DETECTED",
                        label="Prompt injection pattern detected",
                        weight=weight,
                        detail=pattern.pattern,
                    )
                )

        return findings


def _extract_text(request: ChatCompletionRequest) -> str:
    parts = []
    for msg in request.messages:
        if isinstance(msg.content, str):
            parts.append(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)
