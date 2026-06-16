# AI API Gateway

An open-source AI API Gateway with multi-provider routing and OWASP LLM security guardrails. Implements the OpenAI chat completions API subset — point your existing OpenAI SDK client at the gateway and get secret detection, PII redaction, prompt injection blocking, audit logging, and fallback routing for free.

> **Compatibility scope:** `POST /v1/chat/completions` and `GET /v1/models` are implemented. The gateway is not a full OpenAI API replacement — endpoints like Assistants, Files, Embeddings, Images, and Fine-tuning are not supported.

---

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — add at least one GATEWAY_API_KEYS value and one provider key

# 2. Start everything
docker compose up

# 3. Test it
curl http://localhost:8000/gateway/health
```

That's it. The gateway starts with Presidio (PII), Gitleaks (secrets), and Ollama (local models) alongside it.

---

## What's Inside

| Feature | How |
|---|---|
| **Multi-provider routing** | OpenAI, Anthropic, Google Gemini, Ollama — model prefix auto-routes |
| **OpenAI-compatible API** | Existing OpenAI SDK clients work with `base_url` change only |
| **Prompt injection detection** | 10 regex patterns, block or flag mode |
| **Secret detection** | 222 Gitleaks rules (full official ruleset) — GitHub/GitLab PATs, AWS keys, Slack tokens, private keys, and more |
| **PII redaction** | Microsoft Presidio — SSN, credit cards, emails, names, phone numbers, and more |
| **Risk scoring** | Every request scored 0–100 with severity label and reasons |
| **RBAC policies** | Per-API-key allow/deny model lists via `config/policies.yaml` |
| **Fallback routing** | Automatic failover chain if a provider is down |
| **Audit logging** | Every request logged to SQLite with tokens, cost, latency, risk |
| **Prometheus metrics** | `/metrics` endpoint — requests, tokens, cost, latency, security events |
| **Per-key rate limiting** | RPM + TPM tumbling minute window per API key |

---

## Architecture

See [HLD.md](HLD.md) for high-level system and deployment diagrams, [LLD.md](LLD.md) for module-level diagrams, and [ARCHITECTURE.md](ARCHITECTURE.md) for the full service graph, request lifecycle sequence diagram, and component map.

**Service summary:**

```
Client (OpenAI SDK)
    ↓
Gateway :8000          ← your FastAPI app (thin — no NLP deps)
    ├── Presidio Analyzer  :3000  (mcr.microsoft.com/presidio-analyzer)
    ├── Presidio Anonymizer :3000 (mcr.microsoft.com/presidio-anonymizer)
    ├── Gitleaks Sidecar   :8080  (ghcr.io/gitleaks/gitleaks + FastAPI wrapper)
    └── Ollama             :11434 (local models)
```

---

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
# Required
GATEWAY_API_KEYS=your-secret-key-here   # comma-separated for multiple keys
OPENAI_API_KEY=sk-...                   # leave blank to disable OpenAI

# Optional providers (leave blank to disable)
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

# Security pipeline
PIPELINE_INJECTION_MODE=block     # block | flag
PIPELINE_PII_MODE=redact          # redact | flag | off
RISK_SCORE_BLOCK_THRESHOLD=75     # 0-100

# Production hardening
VERBOSE_ERRORS=false              # hides risk details from response body
SIDECAR_FAIL_CLOSED=true          # block requests when sidecars are unreachable
CORS_ALLOWED_ORIGINS=https://app.example.com

# Rate limiting (per API key per minute)
RATE_LIMIT_RPM=100
RATE_LIMIT_TPM=0                  # 0 = unlimited
```

### Full reference

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_API_KEYS` | *(empty — auth off)* | Comma-separated valid API keys |
| `OPENAI_API_KEY` | | OpenAI API key |
| `ANTHROPIC_API_KEY` | | Anthropic API key |
| `GOOGLE_API_KEY` | | Google Gemini API key |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama endpoint |
| `PRESIDIO_ANALYZER_URL` | `http://presidio-analyzer:3000` | Set by docker-compose |
| `PRESIDIO_ANONYMIZER_URL` | `http://presidio-anonymizer:3000` | Set by docker-compose |
| `GITLEAKS_SIDECAR_URL` | `http://gitleaks-sidecar:8080` | Set by docker-compose |
| `PIPELINE_INJECTION_MODE` | `block` | `block` or `flag` |
| `PIPELINE_PII_MODE` | `redact` | `redact`, `flag`, or `off` |
| `RISK_SCORE_BLOCK_THRESHOLD` | `75` | Score (0–100) above which requests are blocked |
| `VERBOSE_ERRORS` | `true` | Include risk details in 400 responses |
| `SIDECAR_FAIL_CLOSED` | `false` | Block requests if a sidecar is unreachable |
| `CORS_ALLOWED_ORIGINS` | *(empty — deny all)* | Comma-separated allowed origins |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Max request body size (1 MB) |
| `RATE_LIMIT_RPM` | `100` | Max requests per minute per API key |
| `RATE_LIMIT_TPM` | `0` | Max tokens per minute (0 = unlimited) |
| `POLICY_FILE` | `config/policies.yaml` | RBAC policy file path |
| `DB_PATH` | `gateway.db` | SQLite database file |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |
| `GATEWAY_ENV` | `development` | Set to `production` to enable startup safety checks |
| `PIPELINE_STREAM_MODE` | `buffered` | `buffered` (safe, adds latency) or `passthrough` (true streaming, no output PII scan) |

---

## API Reference

### OpenAI-compatible endpoints

The gateway implements the chat completions subset of the OpenAI API. Use the standard OpenAI Python SDK by pointing `base_url` at the gateway:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-gateway-key",
)

response = client.chat.completions.create(
    model="gpt-4o",          # routes to OpenAI
    # model="claude-sonnet-4-6",   # routes to Anthropic
    # model="gemini-1.5-pro",      # routes to Google
    # model="llama3.2",            # routes to Ollama
    messages=[{"role": "user", "content": "Hello!"}],
)
```

#### `POST /v1/chat/completions`

Standard OpenAI chat completions. Supports streaming (`"stream": true`).

**Streaming behaviour:**

| Mode (`PIPELINE_STREAM_MODE`) | Behaviour |
|---|---|
| `buffered` *(default)* | The full response is buffered internally, output PII scan runs on the assembled text, then chunks are re-emitted as SSE. Safe, but the caller receives nothing until generation is complete. The `x-gateway-stream-mode: buffered` header signals this. |
| `passthrough` | Chunks are forwarded as they arrive (true low-latency streaming). Output PII scanning is **skipped** — PII in LLM responses will not be redacted. Use only when latency matters more than output sanitisation. |

> **Note:** Streaming responses do not record token usage or cost in the audit log, and they do not participate in the fallback chain. If the provider fails mid-stream, the client receives an inline error chunk rather than a retry on a fallback model.

**Extended gateway fields on the request:**

| Field | Type | Description |
|---|---|---|
| `provider` | `string` | Force a specific provider: `openai`, `anthropic`, `google`, `ollama` |

**Response headers added by the gateway:**

| Header | Description |
|---|---|
| `x-gateway-risk-score` | Request risk score (0–100) |
| `x-gateway-risk-severity` | `low`, `medium`, `high`, or `critical` |
| `x-gateway-risk-reasons` | Comma-separated detection labels (if `VERBOSE_ERRORS=true`) |
| `x-gateway-request-id` | UUID for tracing this request in audit logs |
| `x-gateway-pii-output` | PII entity types redacted from the response |
| `x-gateway-stream-mode` | `buffered` or `passthrough` — only present on streaming responses |

#### `GET /v1/models`

Returns all models available across all configured providers.

---

### Gateway endpoints

#### `GET /gateway/health`

No auth required. Returns per-provider status.

```json
{
  "status": "ok",
  "providers": [
    {"name": "openai", "available": true, "models": ["gpt-4o", "gpt-4o-mini"]},
    {"name": "anthropic", "available": true, "models": ["claude-sonnet-4-6"]},
    {"name": "ollama", "available": false, "error": "connection refused"}
  ]
}
```

#### `GET /gateway/stats`

Requires API key. In-memory counters (reset on restart — use `/gateway/audit` for persistence).

```json
{
  "requests_total": 1420,
  "requests_blocked": 12,
  "pii_detections": 34,
  "injection_detections": 8
}
```

#### `GET /gateway/audit?limit=100&offset=0`

Requires API key. Paginated audit log from SQLite.

```json
{
  "total": 100,
  "offset": 0,
  "limit": 100,
  "data": [
    {
      "request_id": "3fa85f64-...",
      "timestamp": "2026-06-16T10:22:11+00:00",
      "api_key_hash": "e3b0c44298fc...",
      "model": "gpt-4o",
      "provider": "openai",
      "blocked": 0,
      "risk_score": 15,
      "severity": "low",
      "reasons": "[]",
      "latency_ms": 842.3,
      "input_tokens": 120,
      "output_tokens": 450,
      "cost_usd": 0.00477
    }
  ]
}
```

#### `GET /metrics`

No auth required (standard Prometheus scrape pattern). Exposes:

```
gateway_requests_total{model, provider, status}
gateway_tokens_total{model, token_type}
gateway_security_events_total{code}
gateway_request_duration_seconds{model, provider}
gateway_cost_usd_total{model}
```

---

## RBAC Policies

Copy `config/policies.yaml.example` to `config/policies.yaml`:

```yaml
policies:
  default:
    allowed_models: []   # empty = all models allowed
    denied_models: []

  "finance-team-key":
    allowed_models:
      - gpt-4o
      - claude-sonnet-4-6

  "intern-key":
    denied_models:
      - gpt-4o
      - claude-opus-4-7
```

---

## Fallback Routing

Edit `config/fallbacks.yaml` to define chains used when a provider fails:

```yaml
fallbacks:
  gpt-4o:
    - claude-sonnet-4-6
    - gemini-1.5-pro
```

When `gpt-4o` fails, the gateway automatically retries with `claude-sonnet-4-6`, then `gemini-1.5-pro`, before returning 502.

---

## Security Pipeline

Every request passes through the pipeline in order:

```
Auth → Rate limit → RBAC policy → Prompt injection → Secret scan → PII scan → Provider → PII output scan
```

**Risk scoring:**
- Each detector contributes a weighted `Finding` (weight 10–65 depending on rule)
- Scores aggregate: `min(100, Σ weights)`
- Severity: `low` (0–25) · `medium` (26–50) · `high` (51–75) · `critical` (76–100)
- Requests block if: any secret detected, policy weight ≥ 100, injection in block mode, or score ≥ threshold

**Rate limiting behaviour:**

RPM is enforced before the request reaches the LLM. TPM enforcement is intentionally **delayed by one request** — actual token counts are recorded after the LLM responds, so the next request sees the accumulated total. A single very large request can therefore temporarily exceed the TPM budget before the next request is blocked. This is a known trade-off: enforcing TPM before the request requires estimating output tokens in advance, which is not reliably possible.

**Blocked request response:**
```json
{
  "detail": {
    "code": "PROMPT_INJECTION_DETECTED",
    "message": "Prompt injection pattern detected",
    "risk_score": 40,
    "severity": "medium",
    "reasons": ["Prompt injection pattern detected"]
  }
}
```

Set `VERBOSE_ERRORS=false` in production to hide `risk_score` and `reasons`.

---

## Running Without Docker

```bash
# Install deps
pip install -r requirements.txt

# Point at external sidecars (or set SIDECAR_FAIL_CLOSED=false to skip them)
export PRESIDIO_ANALYZER_URL=http://localhost:3000
export PRESIDIO_ANONYMIZER_URL=http://localhost:3001
export GITLEAKS_SIDECAR_URL=http://localhost:8080
export GATEWAY_API_KEYS=dev-key
export OPENAI_API_KEY=sk-...

python main.py
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests mock all sidecar HTTP calls — no running services required.

---

## Adding a New LLM Provider

1. Create `app/providers/yourprovider.py` implementing `BaseProvider` (`complete`, `stream`, `list_models`, `health_check`)
2. Add it to `app/providers/router.py` — instantiate in `__init__` and add prefix entries to `_PREFIX_MAP`
3. Add the API key to `app/config.py` and `.env.example`

---

## Deployment Notes

- **TLS termination** — put the gateway behind nginx / Caddy / a cloud load balancer for HTTPS. The sidecars communicate over the internal Docker network and do not need their own TLS.
- **Kubernetes** — use a service mesh (Istio, Linkerd) for mTLS between the gateway and sidecars.
- **Database** — `gateway.db` is a SQLite file. Mount it as a persistent volume in production. For high-write loads, swap `app/db.py` for PostgreSQL + asyncpg.
- **Ollama GPU** — add `deploy.resources.reservations.devices` to the `ollama` service in `docker-compose.yml` for GPU access.
