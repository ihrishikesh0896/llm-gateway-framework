"""Allow/deny model access policies per API key (RBAC)."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.pipeline.base import Finding, PreProcessor
from app.schemas.openai_compat import ChatCompletionRequest

logger = logging.getLogger(__name__)


def load_policies(path: str | Path) -> dict:
    try:
        resolved = Path(path).resolve()
        # Guard against path traversal — must stay within cwd or config/
        cwd = Path.cwd().resolve()
        if not str(resolved).startswith(str(cwd)):
            raise ValueError(f"Policy path escapes project root: {resolved}")
        with open(resolved) as f:
            data = yaml.safe_load(f) or {}
        return data.get("policies", {})
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Could not load policy file %s: %s", path, exc)
        return {}


class PolicyEnforcer(PreProcessor):
    """
    Checks the requested model against per-key allow/deny policies.
    The api_key must be injected at request time (set on the request object by auth middleware).
    """

    def __init__(self, policies: dict) -> None:
        self._policies = policies  # keyed by api_key string or "default"

    def scan(self, request: ChatCompletionRequest) -> list[Finding]:
        from app.api.v1.chat import _current_api_key
        api_key: str = _current_api_key.get()
        policy = self._policies.get(api_key) or self._policies.get("default") or {}

        model = request.model
        findings: list[Finding] = []

        allowed: list[str] = policy.get("allowed_models", [])
        denied: list[str] = policy.get("denied_models", [])

        if allowed and model not in allowed:
            findings.append(
                Finding(
                    code="MODEL_NOT_ALLOWED",
                    label=f"Model '{model}' is not in your allowed models list",
                    weight=100,  # always block — policy violation
                    detail=f"allowed: {allowed}",
                )
            )
        elif model in denied:
            findings.append(
                Finding(
                    code="MODEL_DENIED",
                    label=f"Model '{model}' is denied by policy",
                    weight=100,
                    detail=f"denied: {denied}",
                )
            )

        return findings
