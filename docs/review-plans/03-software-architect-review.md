# Plan 3: Software Architect Review

**Perspective:** Software / systems architect evaluating structure, extensibility, and operational readiness
**Core question:** Is this architecture sound for production operation, scaling, and extension?
**Scope:** Package structure, dependency management, configuration, containerization, observability, resilience patterns
**Date:** 2026-02-28

---

## 1. Current Architecture

### 1.1 Component diagram

```
                          ┌─────────────────────────────────────────┐
                          │              User / Agent               │
                          └──────┬──────────┬──────────┬────────────┘
                                 │          │          │
                    ┌────────────▼──┐  ┌────▼─────┐  ┌▼────────────────┐
                    │  CLI          │  │ LangChain │  │ MCP Client      │
                    │ __main__.py   │  │ (external)│  │ (Llama Stack,   │
                    │               │  │           │  │  Cursor, etc.)  │
                    └──────┬────────┘  └────┬──────┘  └──────┬──────────┘
                           │               │                 │
                    ┌──────▼────────┐ ┌────▼──────────┐ ┌───▼──────────────┐
                    │ rhokp.retrieve│ │ rhokp.        │ │ mcp_server/      │
                    │ retrieve()    │ │ retrievers    │ │ server.py        │
                    │ aretrieve()   │ │ OKPLangChain  │ │ search_red_hat_  │
                    │               │ │ Retriever     │ │ docs()           │
                    └──────┬────────┘ └───────┬───────┘ └──────┬───────────┘
                           │                  │                │
                           │          ┌───────▼───────┐        │
                           │          │ rhokp.retrieve │        │
                           │          │ retrieve()     │◄───────┘
                           │          └───────┬────────┘
                           │                  │
                           ▼                  ▼
                    ┌──────────────────────────────────┐
                    │  OKP (Solr)                      │
                    │  GET /solr/portal/select          │
                    │  ?q=...&hl=true&wt=json           │
                    └──────────────────────────────────┘
```

### 1.2 Dependency graph

```
rhokp (core)
  └── httpx >= 0.27.0      (required)

rhokp[langchain]
  └── langchain-core >= 0.3.0, < 0.4

rhokp[mcp]
  └── fastmcp >= 3.0.0

rhokp[observability]
  └── opentelemetry-api >= 1.20.0

rhokp[dev]
  ├── pytest >= 7.0.0
  ├── pytest-cov >= 4.0.0
  ├── pytest-asyncio >= 0.23.0
  ├── ruff >= 0.8.0
  └── mypy >= 1.8.0
```

### 1.3 What exists

| Component | Location | In package? | Installable? |
|-----------|----------|-------------|--------------|
| Core retrieval | `src/rhokp/retrieve.py` | Yes | `pip install rhokp` |
| LangChain adapter | `src/rhokp/retrievers.py` | Yes | `pip install rhokp[langchain]` |
| CLI | `src/rhokp/__main__.py` | Yes | `python -m rhokp` or `rhokp` |
| MCP server | `mcp_server/server.py` | **No** | Only from git clone or container |
| Reference client | `demo/ask_okp.py` | **No** | Only from git clone or container |

---

## 2. Architectural Findings

### 2.1 Package boundary violation: MCP server lives outside the package

**Severity: High**

`mcp_server/server.py` imports from `rhokp` but is not part of the `src/rhokp/` package. This means:

- `pip install rhokp[mcp]` installs `fastmcp` as a dependency but does NOT install the MCP server code
- The server is only usable by cloning the git repo or building the container
- There is no `rhokp.mcp` module that users can import
- The server cannot be started via a console_scripts entry point (e.g., `rhokp-mcp`)

**Impact:** A user who wants to run the MCP server in their own environment (not in a container) must clone the repo and run `python mcp_server/server.py`. This is not how production Python packages work.

**Recommendation:** Move the MCP server into the package:

```
src/rhokp/
  ├── mcp/
  │   ├── __init__.py
  │   └── server.py
  ...
```

Add a console_scripts entry point: `rhokp-mcp = "rhokp.mcp.server:main"`. Guard the import of `fastmcp` so it only fails when someone actually tries to run the server without the extra installed.

### 2.2 No abstraction over the search backend

**Severity: High**

`retrieve.py` is tightly coupled to Solr's query syntax and response format:

- `_solr_params()` constructs Solr-specific query parameters (`q`, `wt`, `hl`, `hl.fl`, `hl.snippets`, `hl.fragsize`)
- `_parse_response()` parses the Solr response format (`response.numFound`, `response.docs`, `highlighting`)
- `_SOLR_PATH = "/solr/portal/select"` hardcodes the Solr endpoint path

If OKP's API evolves (e.g., a REST wrapper over Solr, a new search backend, or a different Solr schema), the entire `retrieve.py` must be rewritten.

**Recommendation:** Introduce a `SearchBackend` protocol:

```python
from typing import Protocol

class SearchBackend(Protocol):
    def search(self, query: str, rows: int) -> tuple[list[OKPDocument], int]: ...
    async def asearch(self, query: str, rows: int) -> tuple[list[OKPDocument], int]: ...
```

The current Solr implementation becomes `SolrBackend`. The `OKPClient` (see 2.3) takes a backend at construction time. This allows:
- Swapping Solr for a different backend without changing callers
- Adding a mock backend for testing without transport-level mocking
- Composing backends (e.g., Solr + vector store for hybrid search)

### 2.3 No client class: stateless function API creates performance problems

**Severity: High**

The public API is two module-level functions: `retrieve()` and `aretrieve()`. Each call:

1. Resolves config from env vars
2. Creates a new `httpx.Client` or `httpx.AsyncClient`
3. Opens a TCP connection (+ TLS if applicable)
4. Makes the HTTP request
5. Closes the connection
6. Destroys the client

In production:
- An MCP server handling 100 queries/minute creates 100 TCP connections/minute
- A batch RAG pipeline processing 1,000 documents creates 1,000 TCP connections
- Each connection pays TCP handshake + optional TLS negotiation latency

**Recommendation:** Introduce an `OKPClient` class:

```python
class OKPClient:
    def __init__(
        self,
        base_url: str | None = None,
        rows: int | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        verify: bool | str = True,
    ):
        # Resolve and validate config ONCE at construction
        # Create persistent httpx.Client with connection pooling
        ...

    def retrieve(self, query: str, *, rows: int | None = None) -> RetrieveResult: ...
    async def aretrieve(self, query: str, *, rows: int | None = None) -> RetrieveResult: ...

    def close(self) -> None: ...
    async def aclose(self) -> None: ...

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.aclose()
```

Keep the module-level `retrieve()` / `aretrieve()` as convenience wrappers that create a one-shot client. The MCP server and LangChain adapter use a persistent client.

### 2.4 Configuration model: per-call env var reads

**Severity: Medium**

```python
def _resolve_config(base_url, rows):
    if base_url is None:
        base_url = os.environ.get("RHOKP_BASE_URL", _DEFAULT_BASE_URL)
    if rows is None:
        rows = int(os.environ.get("RHOKP_RAG_ROWS", str(_DEFAULT_ROWS)))
    return base_url, rows
```

Every `retrieve()` call reads `os.environ`. This means:
- No startup validation (invalid `RHOKP_RAG_ROWS="abc"` only fails on first call)
- No centralized config that can be inspected or logged
- Configuration drift if env vars change mid-process

**Recommendation:** Create an `OKPConfig` dataclass:

```python
@dataclass(frozen=True)
class OKPConfig:
    base_url: str
    rows: int
    timeout: float
    retries: int
    verify: bool | str

    @classmethod
    def from_env(cls) -> "OKPConfig":
        # Read and validate all config from env
        # Raise clear errors for invalid values
        ...
```

Validate at construction. Log the config at startup. Pass it to `OKPClient`.

### 2.5 No resilience patterns

**Severity: High**

The only resilience mechanism is `httpx.HTTPTransport(retries=N)`, which retries on connection-level failures (TCP connect, DNS resolution). There is no:

| Pattern | Current state | Impact |
|---------|--------------|--------|
| Circuit breaker | Missing | If OKP is down, every request blocks for `timeout` seconds before failing |
| Exponential backoff | Missing | Transport retries happen immediately; can hammer a recovering service |
| Bulkhead | Missing | One slow OKP instance blocks all concurrent callers |
| Timeout hierarchy | Missing | No separate timeouts for connect, read, pool acquisition |
| Fallback | Missing | No cached/stale result when OKP is unreachable |
| Request queuing | Missing | Under load, requests pile up without backpressure |

**Recommendation:** For a library, start with:
1. **Timeout hierarchy:** Use httpx's `Timeout(connect=5.0, read=25.0, pool=10.0)` instead of a single flat timeout
2. **Retry with backoff:** Application-level retry with exponential backoff (not just transport-level)
3. **Optional circuit breaker:** A simple in-process circuit breaker (open after N consecutive failures, half-open after cooldown)
4. **Optional response cache:** TTL-based cache for identical queries (configurable, off by default)

### 2.6 Containerization gaps

**Severity: Medium**

| Issue | Current state | Production standard |
|-------|--------------|---------------------|
| Multi-stage build | No (single stage) | Yes -- separate build and runtime stages to minimize image size |
| Pinned pip version | No | Yes -- `pip install --upgrade pip==X.Y.Z` for reproducibility |
| Dependency lock file | No (no `pip-compile`, no `poetry.lock`) | Yes -- deterministic installs |
| Health check | No `HEALTHCHECK` instruction | Yes -- container orchestrators need it |
| Image scanning | Not in CI | Yes -- Trivy, Grype, or equivalent |
| Base image pinning | `latest` tag | Yes -- pin to specific UBI 9 minor version |
| Layer optimization | Good (COPY before RUN pip install) | Good |
| Non-root user | Yes (USER 1001) | Good |
| Secrets handling | Good (runtime env only) | Good |

**Recommendation:**
- Add `HEALTHCHECK` instruction to Dockerfiles
- Pin the base image to a specific version (not `latest`)
- Add a CI job for image vulnerability scanning
- Consider multi-stage builds if image size matters

### 2.7 MCP server: no startup validation, no graceful shutdown

**Severity: Medium**

```python
if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8010"))
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
```

- No validation that OKP is reachable at startup
- No graceful shutdown handler (SIGTERM)
- No startup log message with config summary
- `int(os.environ.get("MCP_PORT", "8010"))` will raise `ValueError` if `MCP_PORT="abc"` -- only at startup, with an unhelful traceback

**Recommendation:** Add startup validation:
1. Validate all config and log it
2. Optionally ping OKP to verify reachability (warn if unreachable, don't block startup)
3. Handle SIGTERM for graceful shutdown
4. Log startup completion with bound address

### 2.8 No observability infrastructure

**Severity: High**

| Capability | Current state | Production requirement |
|------------|--------------|----------------------|
| Structured logging | No (text format) | JSON logs for aggregation |
| Request-id propagation | No | Trace requests across retrieve -> OKP |
| Health endpoint | No | `/health` or `/ready` for orchestrators |
| Metrics | No | Latency histograms, error rates, query counts |
| Distributed tracing | OTel (optional) | Good start, but untested and minimal |
| Alerting hooks | No | Error rate thresholds, latency SLOs |

**Recommendation:**
1. Add structured logging with `structlog` or JSON formatter
2. Add `/health` endpoint to MCP server (and optionally to a standalone health check script for the library)
3. Add Prometheus-compatible metrics (or at minimum, log-based metrics)
4. Expand OTel integration to cover the full request lifecycle, not just `retrieve()`

---

## 3. Target Architecture

### 3.1 Proposed package structure

```
src/rhokp/
  ├── __init__.py           # Public API exports
  ├── __main__.py           # CLI: rhokp "query"
  ├── py.typed              # PEP 561 marker
  ├── config.py             # OKPConfig dataclass, env loading, validation
  ├── client.py             # OKPClient class (persistent httpx, connection pool)
  ├── models.py             # OKPDocument, RetrieveResult, exception hierarchy
  ├── backends/
  │   ├── __init__.py       # SearchBackend protocol
  │   ├── solr.py           # SolrBackend (current retrieve.py logic)
  │   └── mock.py           # MockBackend for testing/development
  ├── adapters/
  │   ├── __init__.py
  │   ├── langchain.py      # OKPLangChainRetriever
  │   └── adk.py            # Future: ADK adapter
  ├── mcp/
  │   ├── __init__.py
  │   └── server.py         # MCP server (was mcp_server/server.py)
  ├── context.py            # Context construction (token-aware, citation-enabled)
  └── observability.py      # OTel, structured logging, metrics
```

### 3.2 Proposed dependency architecture

```
rhokp (core)
  ├── httpx >= 0.27.0
  └── (no other required deps)

rhokp[langchain]
  └── langchain-core >= 0.3.0, < 0.4

rhokp[mcp]
  └── fastmcp >= 3.0.0

rhokp[observability]
  ├── opentelemetry-api >= 1.20.0
  └── structlog >= 24.0.0  (or stdlib JSON logging)

rhokp[all]
  └── all of the above
```

### 3.3 Key architectural decisions needed

| Decision | Options | Recommendation | Rationale |
|----------|---------|----------------|-----------|
| Client vs. function API | (A) Functions only, (B) Client class + function wrappers | **B** | Connection pooling, config-once, context manager support |
| Backend abstraction | (A) Solr-only, (B) Protocol/interface | **B** | Extensibility for hybrid search, mock testing |
| MCP server location | (A) Keep outside package, (B) Move into package | **B** | Installable, discoverable, entry-point-able |
| Caching | (A) No cache, (B) Library-level TTL cache, (C) Server-level cache | **B** | Transparent to callers; configurable TTL |
| Configuration | (A) Per-call env reads, (B) Config object at startup | **B** | Validation, logging, immutability |
| Logging | (A) stdlib text, (B) structlog JSON | **B** | Production aggregation, machine-readable |
| Reference client location | (A) demo/ directory, (B) examples/ directory, (C) CLI subcommand | **C** | `rhokp ask "query"` as a first-class command |

---

## 4. Migration Path

### Phase 1: Foundation (estimated 1 week)

1. Create `OKPConfig` dataclass with `from_env()` and validation
2. Create `OKPClient` class with persistent httpx client and context manager
3. Extract `OKPDocument`, `RetrieveResult`, and exceptions into `models.py`
4. Keep existing `retrieve()` / `aretrieve()` as convenience wrappers
5. Move MCP server into `src/rhokp/mcp/server.py`
6. Add `rhokp-mcp` console_scripts entry point
7. Rename `demo/` to `examples/` (or promote to CLI subcommand)

### Phase 2: Resilience and Observability (estimated 1 week)

1. Add timeout hierarchy to httpx client configuration
2. Add application-level retry with exponential backoff
3. Add structured logging (JSON format)
4. Add `/health` endpoint to MCP server
5. Add startup validation and config logging to MCP server
6. Expand OTel integration to full request lifecycle

### Phase 3: Extensibility (estimated 1 week)

1. Introduce `SearchBackend` protocol
2. Refactor Solr logic into `SolrBackend`
3. Create `MockBackend` for development and testing
4. Add query filtering support (product, version, document kind)
5. Add response caching with configurable TTL

### Phase 4: Containerization and CI (estimated 3 days)

1. Add `HEALTHCHECK` to Dockerfiles
2. Pin base image versions
3. Add image vulnerability scanning to CI
4. Add dependency lock file generation
5. Update CI to test MCP server from package (not from `mcp_server/` directory)

---

## 5. Scorecard

| Area | Rating | Key gap |
|------|--------|---------|
| Package structure | Needs Work | MCP server and reference client outside package |
| Dependency management | Pass | Optional extras well-designed |
| Configuration | Needs Work | Per-call env reads, no validation at startup |
| Connection management | Fail | New TCP connection per call |
| Resilience | Fail | No circuit breaker, no backoff, no caching |
| Containerization | Needs Work | No health check, no image pinning, no scanning |
| Observability | Fail | No structured logging, no health endpoint, no metrics |
| Extensibility | Needs Work | No backend abstraction; hard to add new search backends |
| Testability | Needs Work | Transport-level mocking works but no mock backend for integration testing |
| API design | Pass | Clean, typed, well-named |

---

## 6. Verdict: Refactor or Rewrite?

**Package structure:** Refactor. Move MCP server and reference client into the package. Add missing modules (`config.py`, `client.py`, `models.py`). The existing code is sound; it needs reorganization, not replacement.

**Core retrieval logic:** Refactor. The Solr query construction and response parsing are correct. Wrap them in a `SolrBackend` class behind a `SearchBackend` protocol. Estimated effort: 2-3 days.

**MCP server:** Refactor. Add health check, startup validation, structured responses. Move into package. Estimated effort: 1-2 days.

**Configuration:** Rewrite as a proper config module. The current `_resolve_config` is inadequate for production. Estimated effort: 1 day.

**Observability:** Build from scratch. Nothing production-grade exists today. Estimated effort: 2-3 days.

**Resilience patterns:** Build from scratch. No resilience infrastructure exists. Estimated effort: 2-3 days.

**Total estimated effort for architecture remediation: 2-3 weeks of focused work.**
