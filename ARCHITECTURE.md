# Architecture

For focused design diagrams, see [HLD.md](HLD.md) for the high-level design and [LLD.md](LLD.md) for the low-level module design.

## Service Graph

```mermaid
graph TB
    Client["Client\n(OpenAI SDK / curl)"]

    subgraph Docker Compose
        GW["AI API Gateway\nFastAPI · :8000"]

        subgraph Security Sidecars
            GL["Gitleaks Sidecar\n:8080\nghcr.io/gitleaks/gitleaks"]
            PA["Presidio Analyzer\n:3000\nmcr.microsoft.com/presidio-analyzer"]
            PX["Presidio Anonymizer\n:3000\nmcr.microsoft.com/presidio-anonymizer"]
        end

        subgraph LLM Providers
            OA["OpenAI"]
            AN["Anthropic"]
            GO["Google Gemini"]
            OL["Ollama\n(local) · :11434"]
        end

        DB[("SQLite\ngateway.db")]
    end

    Client -->|"POST /v1/chat/completions\nx-api-key: ..."| GW
    GW -->|secret scan| GL
    GW -->|PII analyze| PA
    GW -->|PII anonymize| PX
    GW -->|routed request| OA
    GW -->|routed request| AN
    GW -->|routed request| GO
    GW -->|routed request| OL
    GW -->|audit log\nrate counters| DB
    GW -->|metrics| Prometheus["Prometheus\nGET /metrics"]
```

## Request Lifecycle

```mermaid
sequenceDiagram
    participant C  as Client
    participant GW as Gateway
    participant GL as Gitleaks Sidecar
    participant PA as Presidio Analyzer
    participant PX as Presidio Anonymizer
    participant P  as LLM Provider
    participant DB as SQLite

    C->>GW: POST /v1/chat/completions

    GW->>GW: Auth (API key · hmac.compare_digest)
    GW->>GW: Per-key rate limit check (RPM / TPM)
    GW->>GW: RBAC policy check (allowed / denied models)
    GW->>GW: Prompt injection scan (regex patterns)

    GW->>GL: POST /scan  {text}
    GL-->>GW: [{rule_id, weight, …}]

    GW->>PA: POST /analyze  {text, entities}
    PA-->>GW: [{entity_type, start, end, score}]

    GW->>PX: POST /anonymize  {text, operators, results}
    PX-->>GW: {text: "[SSN_REDACTED] …"}

    GW->>GW: Compute risk score (0–100)\nBlock if score ≥ threshold\nor injection / secret found

    alt Blocked
        GW-->>C: HTTP 400  {code, severity, risk_score}
    else Allowed
        GW->>P: Forwarded request (redacted input)
        P-->>GW: Completion response

        GW->>PA: POST /analyze  {response text}
        PA-->>GW: PII in output?
        GW->>PX: POST /anonymize  (if PII found)
        PX-->>GW: Redacted response

        GW->>DB: INSERT audit_log
        GW-->>C: HTTP 200  +  x-gateway-risk-* headers
    end
```

## Component Map

```
AI-API-GATEWAY/
├── app/
│   ├── main.py                   FastAPI app factory, middleware, lifespan
│   ├── config.py                 All settings via env vars (pydantic-settings)
│   ├── auth.py                   API key validation — timing-safe (hmac.compare_digest)
│   ├── db.py                     SQLite: audit logs, rate limit counters, cost tracking
│   ├── rate_limit.py             Per-key sliding-window RPM/TPM enforcement
│   ├── metrics.py                Prometheus custom counters and histograms
│   ├── state.py                  In-memory request counters (reset on restart)
│   │
│   ├── api/
│   │   ├── v1/
│   │   │   ├── chat.py           POST /v1/chat/completions  (core inference)
│   │   │   └── models.py         GET  /v1/models
│   │   └── gateway/
│   │       ├── health.py         GET  /gateway/health
│   │       └── admin.py          GET  /gateway/stats  |  GET /gateway/audit
│   │
│   ├── clients/
│   │   ├── gitleaks.py           HTTP client → gitleaks sidecar
│   │   └── presidio.py           HTTP client → presidio-analyzer + anonymizer
│   │
│   ├── pipeline/
│   │   ├── base.py               Finding dataclass, PreProcessor / PostProcessor ABCs
│   │   ├── scoring.py            Risk score aggregation (0–100, severity label)
│   │   ├── pre/
│   │   │   ├── prompt_injection.py   LLM01: regex pattern detection
│   │   │   ├── secret_detection.py   Calls gitleaks sidecar
│   │   │   ├── pii_input.py          Calls Presidio (input side)
│   │   │   └── policy.py             RBAC: allowed / denied model enforcement
│   │   └── post/
│   │       └── pii_output.py         Calls Presidio (output side)
│   │
│   ├── providers/
│   │   ├── base.py               BaseProvider ABC: complete() / stream() / list_models()
│   │   ├── openai.py             OpenAI adapter
│   │   ├── anthropic.py          Anthropic adapter
│   │   ├── google.py             Google Gemini adapter (google-genai SDK)
│   │   ├── ollama.py             Ollama adapter (local models)
│   │   └── router.py             Model-prefix routing + fallback chain resolution
│   │
│   └── schemas/
│       ├── openai_compat.py      OpenAI-compatible request / response models
│       └── gateway.py            Extended gateway schemas
│
├── services/
│   └── gitleaks-sidecar/
│       ├── Dockerfile            Multi-stage: gitleaks binary + python:3.11-slim
│       ├── main.py               FastAPI wrapper around gitleaks binary
│       └── requirements.txt
│
├── config/
│   ├── gitleaks_rules.toml       22 bundled secret detection rules (with weights)
│   ├── fallbacks.yaml            Fallback routing chains per model
│   └── policies.yaml.example    RBAC policy template
│
├── tests/
│   ├── conftest.py
│   ├── test_api.py               API-level tests (mocked providers + sidecars)
│   └── test_pipeline_pre.py      Pipeline unit tests
│
├── docker-compose.yml            Full service graph (gateway + 4 sidecars)
├── Dockerfile                    Gateway image (no NLP deps — thin)
├── pyproject.toml
├── requirements.txt              Pinned runtime deps
└── requirements-dev.txt
```

## Security Pipeline — Data Flow

```
Incoming request
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  AUTH                                                   │
│  • API key presence check                               │
│  • hmac.compare_digest timing-safe comparison           │
│  • Per-key RPM / TPM sliding window                     │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  PRE-PROCESSING PIPELINE                                │
│                                                         │
│  1. Policy Enforcer      (sync)  RBAC allow/deny        │
│  2. Prompt Injection     (sync)  10 regex patterns      │
│  3. Secret Detection     (async) → gitleaks sidecar     │
│  4. PII Input Scan       (async) → Presidio sidecar     │
│                                                         │
│  → Findings collected as Finding(code, label, weight)   │
│  → Risk score = min(100, Σ weights)                     │
│  → Block if: weight≥100 OR secret found OR              │
│              injection+block_mode OR score≥threshold    │
└────────────────────────┬────────────────────────────────┘
                         │ (if not blocked)
                         ▼
┌─────────────────────────────────────────────────────────┐
│  PROVIDER ROUTING                                       │
│  • Model-prefix → provider (gpt-* → OpenAI, etc.)      │
│  • Fallback chain on error (config/fallbacks.yaml)      │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
                  [LLM Provider]
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  POST-PROCESSING PIPELINE                               │
│  • PII Output Scan (async) → Presidio sidecar           │
│    redact / flag / off                                  │
│  • Streaming: buffer → scan → re-stream                 │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  AUDIT + METRICS                                        │
│  • Write to SQLite audit_logs                           │
│  • Increment Prometheus counters                        │
│  • x-gateway-risk-* headers on response                 │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
                    Client response
```
