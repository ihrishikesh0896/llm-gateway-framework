# Low-Level Design

This document shows the low-level module design for the AI API Gateway. It focuses on code-level responsibilities and the internal request flow.

## Internal Component Diagram

```mermaid
flowchart TB
    subgraph App["app package"]
        Main["main.py<br/>FastAPI app factory<br/>middleware<br/>lifespan"]
        Config["config.py<br/>pydantic settings"]
        Auth["auth.py<br/>API key validation"]
        Rate["rate_limit.py<br/>RPM and TPM gates"]
        DB["db.py<br/>SQLite access"]
        Metrics["metrics.py<br/>Prometheus counters"]
        State["state.py<br/>in-memory stats"]

        subgraph API["api"]
            Chat["api/v1/chat.py<br/>chat completions"]
            Models["api/v1/models.py<br/>model list"]
            Health["api/gateway/health.py<br/>provider health"]
            Admin["api/gateway/admin.py<br/>stats and audit"]
        end

        subgraph Pipeline["pipeline"]
            Finding["base.py<br/>Finding, processor ABCs"]
            Scoring["scoring.py<br/>risk assessment"]
            Policy["pre/policy.py<br/>RBAC model policy"]
            Injection["pre/prompt_injection.py<br/>regex checks"]
            Secrets["pre/secret_detection.py<br/>secret findings"]
            PIIInput["pre/pii_input.py<br/>input PII handling"]
            PIIOutput["post/pii_output.py<br/>output PII handling"]
        end

        subgraph Clients["clients"]
            GitleaksClient["gitleaks.py<br/>HTTP sidecar client"]
            PresidioClient["presidio.py<br/>analyze and anonymize client"]
        end

        subgraph Providers["providers"]
            ProviderBase["base.py<br/>BaseProvider"]
            Router["router.py<br/>model routing and fallbacks"]
            OpenAIProvider["openai.py"]
            AnthropicProvider["anthropic.py"]
            GoogleProvider["google.py"]
            OllamaProvider["ollama.py"]
        end

        subgraph Schemas["schemas"]
            OpenAICompat["openai_compat.py<br/>request and response models"]
            GatewaySchemas["gateway.py<br/>health and stats models"]
        end
    end

    Main --> Chat
    Main --> Models
    Main --> Health
    Main --> Admin
    Main --> DB
    Main --> Config

    Chat --> Auth
    Chat --> Rate
    Chat --> Policy
    Chat --> Injection
    Chat --> Secrets
    Chat --> PIIInput
    Chat --> Scoring
    Chat --> Router
    Chat --> PIIOutput
    Chat --> DB
    Chat --> Metrics
    Chat --> State
    Chat --> OpenAICompat

    Secrets --> GitleaksClient
    PIIInput --> PresidioClient
    PIIOutput --> PresidioClient

    Router --> ProviderBase
    Router --> OpenAIProvider
    Router --> AnthropicProvider
    Router --> GoogleProvider
    Router --> OllamaProvider

    Models --> Router
    Health --> Router
    Admin --> DB
    Admin --> State
```

## Chat Completion Flow

```mermaid
flowchart TD
    Start["Request enters<br/>POST /v1/chat/completions"]
    Parse["Pydantic parse<br/>ChatCompletionRequest"]
    AuthStep["require_api_key<br/>Authorization or X-API-Key"]
    RateStep["check_rate_limit<br/>increment request counter"]
    PolicyStep["PolicyEnforcer.scan"]
    InjectionStep["PromptInjectionDetector.scan"]
    SecretStep["SecretDetector.async_scan<br/>Gitleaks sidecar"]
    PiiInputStep["PIIInputDetector.async_scan<br/>Presidio sidecar"]
    RiskStep["compute_risk_score"]
    BlockDecision{"Block request?"}
    BlockAudit["write blocked audit<br/>metrics status=blocked"]
    Resolve["provider_router.resolve"]
    StreamDecision{"stream=true?"}
    NonStream["candidate.complete"]
    FallbackDecision{"provider failed?"}
    Fallback["try fallback model<br/>from config/fallbacks.yaml"]
    RecordTokens["record_tokens<br/>for later TPM checks"]
    OutputScan["PIIOutputScanner.async_process"]
    SuccessAudit["write success audit<br/>metrics tokens, cost, latency"]
    Response["Return JSON response"]
    StreamMode{"PIPELINE_STREAM_MODE"}
    Buffered["buffer provider stream<br/>scan assembled output<br/>re-emit SSE"]
    Passthrough["forward SSE chunks<br/>skip output PII scan"]
    StreamAudit["write stream audit<br/>no token usage"]
    StreamResponse["Return text/event-stream"]

    Start --> Parse --> AuthStep --> RateStep
    RateStep --> PolicyStep --> InjectionStep --> SecretStep --> PiiInputStep --> RiskStep --> BlockDecision
    BlockDecision -- yes --> BlockAudit --> Error["HTTP 400"]
    BlockDecision -- no --> Resolve --> StreamDecision

    StreamDecision -- no --> NonStream
    NonStream --> FallbackDecision
    FallbackDecision -- yes --> Fallback --> NonStream
    FallbackDecision -- no --> RecordTokens --> OutputScan --> SuccessAudit --> Response

    StreamDecision -- yes --> StreamMode
    StreamMode -- buffered --> Buffered --> StreamAudit --> StreamResponse
    StreamMode -- passthrough --> Passthrough --> StreamAudit --> StreamResponse
```

## Pre-Processing Pipeline

```mermaid
flowchart LR
    Request["ChatCompletionRequest"]
    Findings["list[Finding]"]
    Risk["RiskAssessment<br/>score, severity, reasons"]

    subgraph SyncProcessors["sync processors"]
        Policy["PolicyEnforcer<br/>MODEL_NOT_ALLOWED<br/>MODEL_DENIED"]
        Injection["PromptInjectionDetector<br/>PROMPT_INJECTION_DETECTED"]
    end

    subgraph AsyncProcessors["async processors"]
        Secrets["SecretDetector<br/>SECRET_DETECTED"]
        PIIInput["PIIInputDetector<br/>PII_DETECTED<br/>optional input redaction"]
    end

    Request --> Policy --> Findings
    Request --> Injection --> Findings
    Request --> Secrets --> Findings
    Request --> PIIInput --> Findings
    Findings --> Risk
    Risk --> Decision{"Block if<br/>policy violation<br/>secret found<br/>injection in block mode<br/>score over threshold"}
```

## Provider Routing and Fallback

```mermaid
flowchart TD
    Model["Requested model"]
    Forced{"provider field set?"}
    ForcedProvider["Use forced provider<br/>if configured"]
    Prefix["Match model prefix"]
    OpenAI["gpt-, o1-, o3-<br/>OpenAIProvider"]
    Anthropic["claude-<br/>AnthropicProvider"]
    Google["gemini-<br/>GoogleProvider"]
    Default["default<br/>OllamaProvider"]
    Call["Call provider.complete"]
    Failed{"exception?"}
    Chain["fallback_chain(model)<br/>config/fallbacks.yaml"]
    Next["resolve_by_model_name<br/>next fallback model"]
    Done["Return ChatCompletionResponse"]
    UpstreamError["HTTP 502<br/>all providers failed"]

    Model --> Forced
    Forced -- yes --> ForcedProvider --> Call
    Forced -- no --> Prefix
    Prefix --> OpenAI --> Call
    Prefix --> Anthropic --> Call
    Prefix --> Google --> Call
    Prefix --> Default --> Call
    Call --> Failed
    Failed -- no --> Done
    Failed -- yes --> Chain
    Chain -- "next model available" --> Next --> Call
    Chain -- "chain exhausted" --> UpstreamError
```

## Persistence Model

```mermaid
erDiagram
    audit_logs {
        INTEGER id PK
        TEXT request_id
        TEXT timestamp
        TEXT api_key_hash
        TEXT model
        TEXT provider
        INTEGER blocked
        INTEGER risk_score
        TEXT severity
        TEXT reasons
        REAL latency_ms
        INTEGER input_tokens
        INTEGER output_tokens
        REAL cost_usd
    }

    rate_limit_counters {
        TEXT api_key_hash PK
        TEXT window_minute PK
        INTEGER request_count
        INTEGER token_count
    }
```

## Key Runtime Modes

| Mode | Setting | Behavior |
|---|---|---|
| Development mode | `GATEWAY_ENV=development` | Allows fail-open sidecars and verbose errors for local work. |
| Production mode | `GATEWAY_ENV=production` | Startup validation rejects missing API keys, fail-open sidecars, verbose errors, disabled PII scanning, and non-blocking injection mode. |
| Buffered streaming | `PIPELINE_STREAM_MODE=buffered` | Buffers stream output, scans/redacts PII, then re-emits SSE chunks. Safer, higher latency. |
| Passthrough streaming | `PIPELINE_STREAM_MODE=passthrough` | Forwards chunks as they arrive and skips output PII scanning. Lower latency, less safe. |
| PII redaction | `PIPELINE_PII_MODE=redact` | Replaces detected PII before provider calls and after provider responses. |
| PII flagging | `PIPELINE_PII_MODE=flag` | Records findings without mutating text. |
| Fail-closed sidecars | `SIDECAR_FAIL_CLOSED=true` | Blocks requests if security sidecars are unreachable. |
