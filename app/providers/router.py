"""Provider router — resolves model name → provider, with fallback chains."""
from __future__ import annotations

import logging
import os

import yaml

from app.providers.base import BaseProvider
from app.providers.openai import OpenAIProvider
from app.providers.anthropic import AnthropicProvider
from app.providers.google import GoogleProvider
from app.providers.ollama import OllamaProvider
from app.config import settings

logger = logging.getLogger(__name__)

_PREFIX_MAP: list[tuple[tuple[str, ...], str]] = [
    (("gpt-", "o1-", "o3-"), "openai"),
    (("claude-",), "anthropic"),
    (("gemini-",), "google"),
]

_FALLBACK_CONFIG = "config/fallbacks.yaml"


def _load_fallbacks() -> dict[str, list[str]]:
    try:
        with open(_FALLBACK_CONFIG) as f:
            data = yaml.safe_load(f) or {}
        return data.get("fallbacks", {})
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Could not load fallback config: %s", exc)
        return {}


class ProviderRouter:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        if settings.openai_api_key:
            self._providers["openai"] = OpenAIProvider(settings.openai_api_key)
        if settings.anthropic_api_key:
            self._providers["anthropic"] = AnthropicProvider(settings.anthropic_api_key)
        if settings.google_api_key:
            self._providers["google"] = GoogleProvider(settings.google_api_key)
        self._providers["ollama"] = OllamaProvider(settings.ollama_base_url)
        self._fallbacks = _load_fallbacks()

    def resolve(self, model: str, force_provider: str | None = None) -> BaseProvider:
        if force_provider:
            if force_provider not in self._providers:
                raise ValueError(f"Provider '{force_provider}' is not configured")
            return self._providers[force_provider]

        for prefixes, provider_name in _PREFIX_MAP:
            if any(model.startswith(p) for p in prefixes):
                if provider_name in self._providers:
                    return self._providers[provider_name]
                break

        return self._providers["ollama"]

    def fallback_chain(self, model: str) -> list[str]:
        """Return ordered list of model alternatives for fallback routing."""
        return self._fallbacks.get(model, [])

    def resolve_by_model_name(self, model: str) -> BaseProvider | None:
        """Resolve a specific model name to its provider (used in fallback loop)."""
        for prefixes, provider_name in _PREFIX_MAP:
            if any(model.startswith(p) for p in prefixes):
                return self._providers.get(provider_name)
        return self._providers.get("ollama")

    def all_providers(self) -> dict[str, BaseProvider]:
        return self._providers


router = ProviderRouter()
