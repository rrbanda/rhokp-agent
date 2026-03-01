# Architecture: OKP with AI Agents

## Goal

Use the **Red Hat Offline Knowledge Portal (OKP)** as the retrieval source and **Llama Stack** as the LLM backend so AI agents can answer Red Hat product questions grounded in official documentation.

## Agent architecture

The primary deployment is a **Google ADK Custom BaseAgent** (`LlamaStackAgent`) that delegates all agentic orchestration to Llama Stack's Responses API. MCP tools are passed inline via `InputToolMCP` -- no server-side tool registration is needed. This pattern is aligned with [lightspeed-stack](https://github.com/lightspeed-core/lightspeed-stack).

```
┌─────────────────┐     ┌──────────────────────────────────────────────────┐
│  User (browser)  │────▶│  ADK Web UI (adk web)                            │
└─────────────────┘     └─────────────────────┬────────────────────────────┘
                                              │
                        ┌─────────────────────▼────────────────────────────┐
                        │  LlamaStackAgent (Custom BaseAgent)              │
                        │  - llama-stack-client SDK                        │
                        │  - responses.create() with InputToolMCP          │
                        │  - Optional shield moderation (pre-call)         │
                        │  - Response text extraction & tool trace logging │
                        └─────────────────────┬────────────────────────────┘
                                              │
                        ┌─────────────────────▼────────────────────────────┐
                        │  Llama Stack (OpenShift)                         │
                        │  - Responses API: POST /v1/responses             │
                        │  - Server-side tool calling & reasoning          │
                        │  - Safety: /v1/shields, /v1/moderations          │
                        └─────────────────────┬────────────────────────────┘
                                              │
                        ┌─────────────────────▼────────────────────────────┐
                        │  OKP MCP Server (rhokp-mcp)                     │
                        │  Tools: search_red_hat_docs, check_okp_health    │
                        └─────────────────────┬────────────────────────────┘
                                              │
                        ┌─────────────────────▼────────────────────────────┐
                        │  Red Hat Offline Knowledge Portal (OKP)          │
                        │  Solr edismax: /solr/portal/select               │
                        │  Faceting, highlighting, field boosting           │
                        └──────────────────────────────────────────────────┘
```

### Data flow

1. User asks a question in the ADK Web UI.
2. `LlamaStackAgent._run_async_impl()` extracts the message from session events.
3. (Optional) Input shield moderation via `client.moderations.create()`.
4. Agent calls `client.responses.create()` with `tools=[InputToolMCP(...)]`.
5. Llama Stack autonomously decides to call `search_red_hat_docs` via MCP.
6. MCP server queries RHOKP Solr, returns documentation excerpts.
7. Llama Stack synthesizes a grounded answer from tool results.
8. Agent extracts text, logs tool traces, yields an ADK Event.
9. ADK Web UI renders the response.

### Key design decisions

- **`llama-stack-client` SDK** instead of raw httpx for typed access to `responses.create()`, `moderations.create()`, `shields.list()`.
- **MCP tools passed inline** as `InputToolMCP` dicts in the `tools` parameter -- no `scripts/register_toolgroup.py` needed.
- **Shield moderation via `moderations.create()`** (not the `guardrails` parameter), following lightspeed-stack's proven pattern. Gracefully degrades when no shields are registered.
- **Shield naming convention:** `input_` prefix for input-only, `output_` for output-only, `inout_` for both (lightspeed-stack convention).

## Usage patterns

1. **ADK agent with web UI (primary)**
   Run `adk web` to get a browser-based chat interface. The `LlamaStackAgent` handles the full loop: user message -> Llama Stack -> MCP tool calls -> grounded answer.

2. **MCP server standalone**
   Run `rhokp-mcp` to expose RHOKP search as MCP tools for any MCP-compatible client.

3. **Python API / CLI**
   Use `rhokp "query"` from the command line or call `retrieve()` / `aretrieve()` from Python for direct retrieval without an LLM.

## Module architecture

```
agent/                 ADK agent package (pip install rhokp[adk])
├── __init__.py        Exports root_agent for adk web / adk api_server
├── agent.py           LlamaStackAgent(BaseAgent) implementation
└── .env.example       Environment variable template

src/rhokp/
├── models.py          Data types, exceptions, text processing
├── config.py          Validated, immutable configuration
├── client.py          HTTP client with connection pooling, circuit breaker (OKPClient)
├── backends/
│   ├── solr.py        Solr search backend
│   └── mock.py        In-memory mock backend for testing
├── adapters/
│   └── adk.py         Google ADK FunctionTool adapter
├── retrievers.py      LangChain adapter (optional: pip install rhokp[langchain])
├── preprocessing.py   Query synonym expansion
├── reranking.py       Optional cross-encoder reranking
├── logging.py         Structured JSON logging with request-id correlation
├── mcp/
│   └── server.py      FastMCP: search_red_hat_docs, check_okp_health
├── __main__.py        CLI entry point: python -m rhokp "query"
└── __init__.py        Public API exports

containers/
├── mcp-server/        MCP server container (python:3.12-slim)
└── adk-agent/         ADK web UI container (python:3.12-slim)
```

## Local development (Podman Compose)

```yaml
# podman-compose.yaml orchestrates:
services:
  rhokp:       # RHOKP container (port 8080)
  mcp-server:  # MCP server (port 8010), connects to rhokp
  adk-web:     # ADK web UI (port 8000), connects to mcp-server
# Llama Stack runs externally on OpenShift
```

See `podman-compose.yaml` for full configuration. All values come from environment variables.

### OKP Solr alignment

The retrieval client is aligned with OKP's actual Solr configuration:

- OKP uses **edismax** with field boosting (`title^15`, `main_content^10`, `product^8`) -- the client does not override these defaults.
- OKP highlights with **`<b>` tags** and `hl.encoder=html` -- the client strips tags and decodes HTML entities.
- OKP returns **facets** (product, documentKind, version, portal_content_subtype) on every response -- the client parses and exposes them.
- The client supports **filter queries** (`fq`) for product, version, and document kind filtering.
- **Query injection protection** via `sanitize_query()` escapes all Solr special characters.
- CVE/errata-specific fields (`portal_severity`, `cve_threatSeverity`, `portal_advisory_type`, `portal_synopsis`) are captured when present.
- The Solr handler path is **configurable** (`RHOKP_SOLR_HANDLER`), supporting both `/select` (general) and `/select-errata` (errata-specific boosting).
- A `User-Agent: rhokp-agent/<version>` header is sent on all requests for RHOKP telemetry segmentation.

See [review-plans/06-okp-solr-discovery.md](review-plans/06-okp-solr-discovery.md) for the full OKP API discovery.

### RHOKP product alignment

This library is designed for use in RHOKP's target environments:

- **Air-gapped deployments:** No external network calls at runtime. All communication is between local services. See [air-gap-deployment.md](air-gap-deployment.md).
- **Telemetry awareness:** Queries are identifiable via User-Agent header. See [telemetry.md](telemetry.md).
- **Content-type awareness:** Security content (CVEs, errata) is formatted with severity and advisory type in context output.
- **Access tier awareness:** `OKPClient.check_health()` reports indexed document counts, which can indicate whether RHOKP is running with full content (ACCESS_KEY provided) or degraded content.

## Configuration

All endpoints and keys are configured via **environment variables** (see [.env.example](../.env.example) and [running.md](running.md)). No URLs or secrets are hardcoded in the repository.
