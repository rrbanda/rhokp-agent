# Plan 1: Expert Code Review

**Perspective:** Senior engineer / production code reviewer
**Core question:** Is the code correct, robust, and maintainable under production conditions?
**Scope:** All Python source in `src/rhokp/`, `mcp_server/`, `demo/`, and `tests/`
**Date:** 2026-02-28

---

## Methodology

Every file was read line-by-line. Findings are rated:

- **Critical** -- Will cause failures, data loss, or security vulnerabilities in production
- **High** -- Will cause degraded behavior or prevent scaling
- **Medium** -- Will create maintenance burden or confuse contributors
- **Low** -- Improvement opportunity; no immediate risk

---

## 1. `src/rhokp/retrieve.py` (343 lines) -- Core Retrieval Client

### 1.1 Error handling taxonomy is semantically incorrect

**Severity: High**

```python
# Line 307-308
except httpx.HTTPError as exc:
    _handle_http_error(exc, query, t0, resolved_url)
```

`httpx.HTTPError` is the base for all httpx errors. Inside `_handle_http_error`, only three subtypes are checked: `HTTPStatusError`, `ConnectError`, `TimeoutException`. Any other error (e.g., `httpx.DecodingError`, `httpx.TooManyRedirects`, `httpx.InvalidURL`) falls through to the final `raise OKPConnectionError(str(exc))`.

**Problem:** A `DecodingError` (OKP returns invalid JSON) is not a "connection error." A `TooManyRedirects` is not a "connection error." Wrapping everything in `OKPConnectionError` gives callers wrong information for retry/alerting decisions.

**Fix:** Introduce `OKPResponseError` for response-level issues (bad JSON, unexpected content type). Map `DecodingError` and `TooManyRedirects` to it. Reserve `OKPConnectionError` strictly for transport failures.

### 1.2 No connection reuse -- new TCP connection per call

**Severity: High**

```python
# Lines 300-306 (sync)
transport = _transport_override or httpx.HTTPTransport(retries=retries)
with httpx.Client(transport=transport) as client:
    resp = client.get(...)

# Lines 332-338 (async)
transport = _transport_override or httpx.AsyncHTTPTransport(retries=retries)
async with httpx.AsyncClient(transport=transport) as client:
    resp = await client.get(...)
```

Both `retrieve()` and `aretrieve()` create and destroy an httpx client (and underlying TCP connection pool) on every single call. In production:

- A RAG pipeline calling `retrieve()` in a loop opens/closes TCP connections per query
- An MCP server handling concurrent requests creates separate connections to OKP per request
- Connection setup latency (TCP handshake, optional TLS) is paid every time

**Fix:** Provide an `OKPClient` class that holds a persistent `httpx.Client` / `httpx.AsyncClient` and exposes `retrieve()` / `aretrieve()` as methods. Keep the module-level functions as convenience wrappers that create a one-shot client. This is the standard pattern (e.g., `boto3.client()`, `httpx.Client()`).

### 1.3 HTML stripping via regex is fragile

**Severity: Medium**

```python
# Line 46
_HTML_TAG_RE = re.compile(r"<[^>]+>")
```

This regex removes anything that looks like an HTML tag. It works for Solr's highlighting (`<em>`, `</em>`) but:

- Fails on malformed HTML (e.g., `< em>` with a space)
- Does not handle HTML entities (`&lt;`, `&amp;`, `&quot;`)
- Would strip legitimate angle-bracket content in documentation (e.g., `<your-namespace>` in OpenShift docs)
- Does not handle self-closing tags with attributes

For OKP's Solr highlighting (which injects only `<em>` tags), this is practically safe. But it is not documented as limited-scope, and if OKP ever changes its highlighting markup, this breaks silently.

**Fix:** Either (a) document explicitly that this only strips Solr highlight tags and is not a general HTML sanitizer, or (b) replace with a targeted strip that only removes known Solr highlight tags (`<em>`, `</em>`, `<b>`, `</b>`) and decodes common HTML entities.

### 1.4 Snippet truncation uses undocumented magic number

**Severity: Medium**

```python
# Line 162
raw_snippet = snippet_candidates[0][:500] if snippet_candidates else ""
```

The 500-character limit is:
- Not configurable
- Not documented in the API
- Applied silently (no indicator that content was truncated)
- Chosen without documented rationale

Similarly, `hl.fragsize=300` (line 141) and `hl.snippets=2` (line 140) are hardcoded without explanation.

**Fix:** Make snippet max length a parameter (with sensible default). Log or mark when truncation occurs. Document the Solr highlighting parameters and why these values were chosen (or state they are defaults pending tuning).

### 1.5 `_parse_response` has no defensive parsing for malformed data

**Severity: High**

```python
# Lines 145-173
def _parse_response(data: dict) -> tuple[list[OKPDocument], int]:
    response = data.get("response", {})
    num_found = response.get("numFound", 0)
    raw_docs = response.get("docs", [])
    highlighting = data.get("highlighting", {})
    ...
```

If OKP returns unexpected JSON (e.g., `data["response"]` is a string, or `docs` contains non-dict entries, or `highlighting` has a different structure), this will raise `TypeError` or `KeyError` without a clear error message. In production:

- OKP version upgrades could change the Solr response schema
- Network issues could cause partial JSON responses
- Load balancers could return HTML error pages that parse as valid JSON in some edge cases

**Fix:** Wrap `_parse_response` in structured error handling. Validate the expected structure before accessing fields. Raise `OKPResponseError` (new exception) with the raw response body on parse failure. Add tests for malformed input shapes.

### 1.6 Async adapter defeats the purpose of async

**Severity: Medium** (in `retrievers.py`)

```python
# retrievers.py line 79
async def _aget_relevant_documents(self, query: str) -> List[Document]:
    return await asyncio.to_thread(self._get_relevant_documents, query)
```

This wraps the sync `retrieve()` call in `asyncio.to_thread`, which moves it to a thread pool thread. This means:
- The event loop is not blocked (good)
- But a thread pool thread IS blocked for the entire HTTP call duration (bad)
- Under load, this exhausts the default thread pool (8 threads)
- The actual async `aretrieve()` function exists but is not used

**Fix:** Change `_aget_relevant_documents` to call `aretrieve()` directly instead of wrapping the sync version. Import and use `aretrieve` from `rhokp.retrieve`.

### 1.7 Transport override typing is incorrect for async

**Severity: Low**

```python
# retrieve.py line 320
_transport_override: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
```

The async function accepts `httpx.BaseTransport` (sync transport). In tests, a sync `MockTransport` is passed to `httpx.AsyncClient`. This works because httpx internally wraps sync transports, but:
- It is not type-safe (mypy with strict mode would flag this)
- It couples tests to httpx internals
- If httpx removes the sync-transport-in-async-client compatibility, tests break

**Fix:** Use `httpx.AsyncMockTransport` (or async handler) in async tests. Restrict the type to `httpx.AsyncBaseTransport | None` in `aretrieve()`.

### 1.8 OTel span attribute setting outside span context

**Severity: Medium**

```python
# Lines 248-252
if _otel_tracer:
    span = trace.get_current_span()
    span.set_attribute("okp.num_found", num_found)
    span.set_attribute("okp.docs_returned", len(docs))
    span.set_attribute("okp.elapsed_ms", elapsed)
```

`_finalize()` sets attributes on the "current span," but this relies on `_otel_span()` being the context manager wrapping the call site. If `_finalize()` is ever called outside a span context (e.g., in a refactored code path), `trace.get_current_span()` returns a no-op span silently. This is not wrong, but it is fragile coupling.

**Fix:** Pass the span (or a span-like object) explicitly to `_finalize()` instead of relying on thread-local context.

### 1.9 `_otel_span` return type annotation is incomplete

**Severity: Low**

```python
# Line 199
def _otel_span(name: str, query: str, rows: int, base_url: str):  # type: ignore[return]
```

The `# type: ignore[return]` suppresses a real type issue. The function returns either a span context manager or `nullcontext()`, but these have different types. This is masked with a type ignore comment.

**Fix:** Add proper return type `contextlib.AbstractContextManager` or `ContextManager[Any]`.

---

## 2. `src/rhokp/retrievers.py` (82 lines) -- LangChain Adapter

### 2.1 No support for LangChain callbacks/tracing

**Severity: Medium**

The `_get_relevant_documents` method does not accept or propagate `run_manager` (the LangChain callback manager). This means:
- LangChain tracing (LangSmith, custom callbacks) cannot observe retrieval calls
- The retriever is invisible in LangChain trace views
- Production debugging of RAG chains is harder

**Fix:** Accept `run_manager: Optional[CallbackManagerForRetrieverRun] = None` in `_get_relevant_documents` and emit events via `run_manager.on_retriever_start/end` if present.

### 2.2 Error swallowing without structured reporting

**Severity: Medium**

```python
# Lines 64-68
except (OKPError, ValueError) as exc:
    if self.raise_on_error:
        raise RuntimeError(str(exc)) from exc
    logger.warning("OKPLangChainRetriever: %s", exc)
    return []
```

When `raise_on_error=False` (default), OKP failures are silently swallowed and an empty list is returned. In a production RAG chain, this means:
- The LLM receives no context and hallucinates
- No one is alerted that retrieval is failing
- The user gets a confidently wrong answer

**Fix:** At minimum, the error should be propagated via LangChain callbacks so tracing catches it. Consider adding a `fallback_context` option or raising by default in production configurations.

### 2.3 Missing `search_type` and `search_kwargs` support

**Severity: Low**

Production LangChain retrievers commonly support `search_type` (similarity, mmr, similarity_score_threshold) and `search_kwargs` (filter, k, etc.). This adapter supports none of these, which means it cannot be used as a drop-in replacement in existing LangChain RAG pipelines that configure search behavior.

**Fix:** Add `search_kwargs` passthrough (map `k` to `rows`, `filter` to Solr `fq` if supported).

---

## 3. `mcp_server/server.py` (53 lines) -- MCP Server

### 3.1 No health check endpoint

**Severity: High**

There is no `/health` or `/ready` endpoint. In production:
- Container orchestrators (Kubernetes, Podman) cannot perform health checks
- Load balancers cannot determine if the service is ready
- The service could be running but OKP could be unreachable, with no way to detect this

**Fix:** Add a health endpoint that checks OKP reachability (or at minimum returns service status). FastMCP supports custom routes.

### 3.2 Returns unstructured strings

**Severity: Medium**

```python
# Lines 41
return result.context or "No results found."
```

The MCP tool returns a plain string. The calling agent has no way to know:
- How many documents were found
- Whether the results are complete or truncated
- Source URLs for citation
- Whether an error occurred vs. genuinely no results

**Fix:** Return structured data (JSON string with `num_found`, `docs`, `context`, `query`). MCP tool responses can carry structured content.

### 3.3 No request-level error isolation

**Severity: Medium**

If `retrieve()` raises an unexpected exception (e.g., `TypeError` from malformed OKP response), it propagates through FastMCP and could crash the server or return an MCP protocol error. Only `OKPError` and `ValueError` are caught.

**Fix:** Add a broad `except Exception` with structured error logging and a safe error response. Never let an unhandled exception reach the MCP transport layer.

### 3.4 Configuration re-read on every request

**Severity: Low**

`retrieve()` calls `_resolve_config()` on every invocation, which reads `os.environ` each time. This is technically correct (env vars can change) but in a server context, configuration should be validated at startup and reused.

**Fix:** Read config once at server startup, validate it, and pass explicitly to `retrieve()`.

---

## 4. `demo/ask_okp.py` (138 lines) -- Reference Client

*Note: This file is labeled "demo" but is the primary reference for OKP + LLM integration. It must be evaluated as production code.*

### 4.1 Hardcoded model default

**Severity: High**

```python
# Line 32
MODEL = os.environ.get("MODEL", "gemini/models/gemini-2.5-flash")
```

The default model is a specific Gemini model name. This:
- Breaks if the user is using a different LLM backend
- Couples to Llama Stack's model naming convention
- Is not documented as requiring Gemini specifically

**Fix:** Remove the default model or use a clearly generic placeholder that forces the user to set it. Document supported model formats.

### 4.2 Response parsing is brittle

**Severity: High**

```python
# Lines 71-94
def _extract_text(response: dict) -> str | None:
    out = response.get("output") or response.get("output_text") or response
    if isinstance(out, list):
        for item in out:
            ...
```

This function tries multiple response shapes (list of messages, dict with content, nested content parts). This is defensive coding for an unstable API, but:
- It has no version detection (which Llama Stack API version produces which shape?)
- If all shapes fail, it returns `None` and the caller dumps raw JSON -- not a production behavior
- No logging of which shape was matched, making debugging impossible

**Fix:** Pin to a specific Llama Stack API version. Document the expected response shape. Raise a clear error if the response doesn't match, with the raw response logged for debugging.

### 4.3 `SystemExit` used for error handling

**Severity: Medium**

```python
# Lines 43, 66, 68
raise SystemExit("Set LLAMA_STACK_BASE to your Llama Stack base URL.")
raise SystemExit(f"Responses API error {exc.response.status_code}: {detail}")
raise SystemExit(f"Request failed: {exc}")
```

`SystemExit` terminates the process. If this code is ever imported as a library (e.g., in a web service or agent framework), these `SystemExit` calls will crash the host process.

**Fix:** Use proper exception hierarchy. `SystemExit` is only acceptable in `if __name__ == "__main__"` blocks.

### 4.4 No timeout configuration for LLM calls

**Severity: Medium**

```python
# Line 61
timeout=120.0,
```

The LLM call has a hardcoded 120-second timeout. No env var override, no documentation of why 120 seconds. In production, this should be configurable and should have a retry strategy.

---

## 5. Tests (568 lines across 5 files)

### 5.1 No malformed-input tests for `_parse_response`

**Severity: High**

`_parse_response` is tested only with well-formed Solr responses (`SOLR_SUCCESS`, `SOLR_EMPTY`). No tests for:
- Missing `response` key
- `docs` containing non-dict entries
- `highlighting` with unexpected structure
- Extremely large responses (memory)
- Unicode edge cases in titles/snippets

**Fix:** Add a `TestParseResponseEdgeCases` class with malformed input tests.

### 5.2 No integration tests

**Severity: Medium**

All tests use mocked transports. There is no integration test that hits a real Solr instance (even a test container). This means:
- Solr query parameter changes are not caught
- Response schema changes from OKP updates are not caught
- The actual HTTP flow (redirects, TLS, compression) is never tested

**Fix:** Add an optional integration test suite (behind a `pytest.mark.integration` marker) that runs against a Solr test container.

### 5.3 No performance / load tests

**Severity: Medium**

No benchmarks for:
- `retrieve()` latency under concurrent calls
- Connection pool exhaustion behavior
- Memory usage with large result sets
- MCP server throughput

**Fix:** Add a `benchmarks/` directory with locust or pytest-benchmark tests.

### 5.4 Test for OTel spans is missing

**Severity: Low**

OTel integration is a production feature but has zero test coverage. Span creation, attribute setting, and the `_otel_tracer is None` path are all untested.

---

## 6. Cross-cutting issues

### 6.1 No input sanitization against Solr injection

**Severity: Critical**

```python
# Lines 133-142
def _solr_params(query: str, rows: int) -> dict:
    return {
        "q": query,
        ...
    }
```

The user's query string is passed directly as the Solr `q` parameter. Solr's query parser supports special syntax:
- `*:*` returns all documents
- `title:secret AND main_content:internal` targets specific fields
- `{!lucene}` switches query parsers
- Query-time boosts and functions can be injected

If OKP is deployed in any environment where query input comes from untrusted sources (e.g., a public-facing chatbot), this is a **Solr injection vulnerability**.

**Fix:** Escape Solr special characters in the query string (`+ - && || ! ( ) { } [ ] ^ " ~ * ? : \`). Or use Solr's `edismax` parser with `qf` (query fields) restriction, which limits what the query can access.

### 6.2 No TLS verification configuration

**Severity: High**

The httpx clients are created with default TLS settings. There is no way to:
- Provide a custom CA bundle (required for internal Red Hat deployments with custom CAs)
- Disable TLS verification for development (insecure but sometimes needed)
- Configure client certificates (mTLS)

**Fix:** Add `verify` and `cert` parameters to `retrieve()` / `aretrieve()`, or accept them via the `OKPClient` class constructor.

### 6.3 No structured logging

**Severity: Medium**

All logging uses basic Python `logging` with string formatting:

```python
logger.info("OKP query=%r num_found=%d ...", query, num_found, ...)
```

In production:
- Log aggregators (ELK, Splunk, CloudWatch) need structured JSON logs
- Request-id correlation is not possible
- Log levels are not configurable per-component

**Fix:** Use structured logging (e.g., `structlog` or JSON formatter). Add request-id propagation.

---

## Scorecard

| Area | Rating | Summary |
|------|--------|---------|
| Correctness | Needs Work | Error taxonomy is misleading; parser lacks defensive handling |
| Security | Fail | Solr injection risk; no TLS config; no input sanitization |
| Robustness | Fail | No connection pooling; no circuit breaker; no caching |
| Performance | Needs Work | New TCP connection per call; no benchmarks |
| Async quality | Needs Work | LangChain async wraps sync in thread; transport type mismatch |
| Test coverage | Needs Work | Happy path covered; edge cases, integration, and performance missing |
| Maintainability | Pass | Clean structure, good naming, consistent patterns |
| Type safety | Needs Work | OTel type ignore; transport override typing incorrect |
| Observability | Needs Work | OTel optional but untested; no structured logging; no health check |

---

## Verdict: Refactor or Rewrite?

**`retrieve.py`:** Refactor in place. The core logic (query Solr, parse response, build context) is correct. The structure is clean. It needs: an `OKPClient` class wrapper, defensive parsing, input sanitization, and proper error taxonomy. Estimated effort: 2-3 days.

**`retrievers.py`:** Refactor in place. Add async `aretrieve()` call, LangChain callback support, and `search_kwargs` passthrough. Estimated effort: 1 day.

**`mcp_server/server.py`:** Refactor in place. Add health check, structured response, error isolation, startup config validation. Estimated effort: 1 day.

**`demo/ask_okp.py`:** Rewrite. The response parsing is too brittle, the error handling pattern (`SystemExit`) is wrong for anything beyond a script, and the hardcoded defaults make it unusable as-is. Promote to a proper CLI command or a well-structured examples module. Estimated effort: 2 days.

**Tests:** Significant additions needed. Estimated effort: 3-4 days for edge-case tests, integration tests, and performance baselines.
