from __future__ import annotations

from typing import Any, Literal, Tuple, Type
from pydantic import Field
from pydantic_settings import BaseSettings, EnvSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

__all__ = ["settings"]

# pydantic-settings 2.x calls json.loads() on list[str] fields before field
# validators run, so comma-separated env values like "key1,key2" crash with
# JSONDecodeError before the validator ever fires. This subclass intercepts
# only the two list fields and splits them early; all other fields go through
# the normal JSON path.
_COMMA_SEP_FIELDS = frozenset({"gateway_api_keys", "cors_allowed_origins"})


class _CommaSepEnvSource(EnvSettingsSource):
    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        if field_name in _COMMA_SEP_FIELDS and isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        return super().decode_complex_value(field_name, field, value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # Patch both sources so comma-sep handling works whether the values
        # come from actual OS env vars (Docker) or the .env file (local dev).
        for src in (env_settings, dotenv_settings):
            src.__class__ = type(
                src.__class__.__name__,
                (_CommaSepEnvSource, src.__class__),
                {},
            )
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    # Gateway auth
    gateway_api_keys: list[str] = Field(default_factory=list)

    # Provider credentials
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Sidecar service URLs (internal Docker network — no TLS needed within compose)
    presidio_analyzer_url: str = "http://presidio-analyzer:3000"
    presidio_anonymizer_url: str = "http://presidio-anonymizer:3000"
    gitleaks_sidecar_url: str = "http://gitleaks-sidecar:8080"

    # When True: sidecar unreachability blocks the request (fail-closed).
    # When False: log warning and continue (fail-open, friendlier for dev).
    sidecar_fail_closed: bool = False

    # Pipeline behaviour
    pipeline_injection_mode: Literal["block", "flag"] = "block"
    pipeline_pii_mode: Literal["redact", "flag", "off"] = "redact"

    # Risk scoring — requests with aggregate score >= this are blocked
    risk_score_block_threshold: int = 75

    # RBAC policy file (relative to project root or absolute)
    policy_file: str = "config/policies.yaml"

    # Rate limiting (requests per minute, applied per API key)
    rate_limit_rpm: int = 100
    # Token budget per minute per API key (0 = unlimited)
    rate_limit_tpm: int = 0

    # Expose full rejection details (risk score, reasons) — disable in production
    verbose_errors: bool = True

    # Environment — set to "production" to enable startup safety checks
    gateway_env: Literal["development", "production"] = "development"

    # Streaming output PII scan mode:
    #   buffered   — buffer the full stream, run PII scan, re-emit (safe, default)
    #   passthrough — true streaming, output PII scan skipped (faster, less safe)
    pipeline_stream_mode: Literal["buffered", "passthrough"] = "buffered"

    # CORS — comma-separated list of allowed origins; empty = deny all cross-origin
    cors_allowed_origins: list[str] = Field(default_factory=list)

    # Maximum request body size in bytes (default 1 MB)
    max_request_body_bytes: int = 1 * 1024 * 1024

    # Persistent storage
    db_path: str = "gateway.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

settings = Settings()
