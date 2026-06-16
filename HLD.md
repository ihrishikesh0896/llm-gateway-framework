# High-Level Design

This document shows the high-level architecture for the AI API Gateway. It focuses on system boundaries, deployment topology, and the main request path.

## System Context

```mermaid
flowchart LR
    Client["Client applications<br/>OpenAI SDK, curl, services"]
    Admin["Operators<br/>health, audit, metrics"]

    subgraph GatewayBoundary["AI API Gateway"]
        Gateway["FastAPI Gateway<br/>OpenAI chat API subset"]
        Policy["Security and governance<br/>auth, rate limits, RBAC, risk scoring"]
    end

    subgraph Sidecars["Security sidecars"]
        Gitleaks["Gitleaks Sidecar<br/>secret detection"]
        PresidioAnalyzer["Presidio Analyzer<br/>PII detection"]
        PresidioAnonymizer["Presidio Anonymizer<br/>PII redaction"]
    end

    subgraph Providers["LLM providers"]
        OpenAI["OpenAI"]
        Anthropic["Anthropic"]
        Google["Google Gemini"]
        Ollama["Ollama<br/>local models"]
    end

    Storage[("SQLite<br/>audit logs and rate counters")]
    Metrics["Prometheus scrape<br/>/metrics"]
    Config["Environment and YAML config<br/>.env, policies, fallbacks"]

    Client -->|"POST /v1/chat/completions"| Gateway
    Client -->|"GET /v1/models"| Gateway
    Admin -->|"GET /gateway/health<br/>GET /gateway/stats<br/>GET /gateway/audit"| Gateway
    Admin -->|"scrape"| Metrics

    Gateway --> Policy
    Policy --> Gitleaks
    Policy --> PresidioAnalyzer
    Policy --> PresidioAnonymizer
    Gateway -->|"routed completion request"| OpenAI
    Gateway -->|"routed completion request"| Anthropic
    Gateway -->|"routed completion request"| Google
    Gateway -->|"routed completion request"| Ollama
    Gateway --> Storage
    Gateway --> Metrics
    Config --> Gateway
```

## Deployment View

```mermaid
flowchart TB
    subgraph Host["Docker host or compose environment"]
        subgraph GatewayContainer["gateway container"]
            API["uvicorn<br/>app.main:app<br/>port 8000"]
        end

        subgraph SecurityContainers["security sidecar containers"]
            GL["gitleaks-sidecar<br/>FastAPI wrapper<br/>port 8080"]
            PA["presidio-analyzer<br/>port 3000"]
            PX["presidio-anonymizer<br/>port 3000"]
        end

        subgraph LocalProvider["optional local provider"]
            OL["ollama<br/>port 11434<br/>ollama_data volume"]
        end

        DB[("gateway.db<br/>SQLite file")]
        Rules["config/gitleaks_rules.toml<br/>mounted read-only"]
        Env["env file<br/>.env.dev, .env.local, .env.prod"]
    end

    ExternalClient["External client"] -->|"localhost:8000"| API
    API -->|"http://gitleaks-sidecar:8080/scan"| GL
    API -->|"http://presidio-analyzer:3000/analyze"| PA
    API -->|"http://presidio-anonymizer:3000/anonymize"| PX
    API -->|"http://ollama:11434/api/chat"| OL
    API --> DB
    GL --> Rules
    Env --> API

    API -.->|"HTTPS via SDKs"| CloudProviders["Cloud LLM APIs<br/>OpenAI, Anthropic, Google"]
```

## Request Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant G as Gateway API
    participant P as Pre-processing
    participant S as Sidecars
    participant R as Provider Router
    participant L as LLM Provider
    participant O as Post-processing
    participant D as SQLite
    participant M as Metrics

    C->>G: POST /v1/chat/completions
    G->>G: Validate API key
    G->>G: Check RPM and prior TPM window
    G->>P: Run policy and prompt-injection checks
    P->>S: Secret scan and PII input scan
    S-->>P: Findings and optional redacted input
    P-->>G: Findings
    G->>G: Compute risk score and block decision

    alt Blocked request
        G->>D: Write blocked audit event
        G->>M: Increment request and security metrics
        G-->>C: HTTP 400
    else Allowed request
        G->>R: Resolve provider by model or forced provider
        R-->>G: Provider adapter
        G->>L: Completion request
        L-->>G: Completion response
        G->>G: Record token usage for future TPM checks
        G->>O: Output PII scan or configured stream mode
        O->>S: Analyze and anonymize output when enabled
        O-->>G: Final response
        G->>D: Write success audit event
        G->>M: Increment request, token, latency, cost metrics
        G-->>C: HTTP 200 or text/event-stream
    end
```

## High-Level Responsibilities

| Area | Responsibility |
|---|---|
| API Gateway | Exposes OpenAI-compatible chat and model endpoints, gateway health, audit, stats, and metrics. |
| Security pipeline | Enforces API key auth, rate limits, RBAC policies, prompt-injection checks, secret detection, PII detection, and risk scoring. |
| Provider routing | Maps models to providers by prefix and applies configured fallback chains for non-streaming completions. |
| Sidecars | Keep heavy or specialized security tooling out of the gateway runtime image. |
| Persistence | Stores audit events and rate-limit counters in SQLite. |
| Observability | Exposes Prometheus metrics and lightweight admin endpoints. |
| Configuration | Uses environment variables for runtime settings and YAML files for policies and fallbacks. |
