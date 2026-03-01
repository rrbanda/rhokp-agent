# Maturity Scorecard: rhokp-agent v0.5.0 Architecture Review

**Date:** 2026-02-28
**Context:** Review conducted against the RHOKP product's actual capabilities, constraints, and deployment model as documented in the RHOKP internal FAQ.

---

## What has been resolved

The v0.4.0 rewrite and v0.5.0 architecture review addressed the following critical findings from the original five-plan review:

### From Plan 1 (Expert Code Review)

| Finding | Status | Implementation |
|---------|--------|----------------|
| Solr query injection | **Resolved** | `sanitize_query()` escapes all Solr special characters |
| No connection pooling | **Resolved** | `OKPClient` with persistent httpx.Client |
| `<em>` vs `<b>` tag mismatch | **Resolved** | Regex targets `<b>` tags, matching OKP's Solr config |
| HTML entities not decoded | **Resolved** | `html.unescape()` after tag stripping |
| Missing `score`, `product`, `version` | **Resolved** | Full field capture in `OKPDocument` |

### From Plan 2 (Product Manager Review)

| Finding | Status | Implementation |
|---------|--------|----------------|
| No product/version filtering | **Resolved** | `fq` params for product, version, document_kind |
| Stale documentation | **Resolved** | Planning artifacts cleaned in v0.4.0 |
| "Demo" framing | **Partially resolved** | Demo remains as a reference client; MCP server is now a proper package module |
| No health check | **Resolved** | `check_okp_health` MCP tool + `OKPClient.check_health()` method |

### From Plan 3 (Software Architect Review)

| Finding | Status | Implementation |
|---------|--------|----------------|
| No client class | **Resolved** | `OKPClient` with context manager, connection pooling |
| Per-call env reads | **Resolved** | `OKPConfig` frozen dataclass with `from_env()` |
| MCP server outside package | **Resolved** | Moved to `src/rhokp/mcp/server.py`; `rhokp-mcp` entry point |
| No startup validation | **Resolved** | Config validates at construction; MCP logs config at startup |
| No timeout hierarchy | **Resolved** | Separate connect, read, pool timeouts |
| No HEALTHCHECK in Dockerfiles | **Resolved** | Added to MCP server Dockerfile |
| Base image not pinned | **Resolved** | Pinned to specific UBI 9 version |

### From Plan 4 (AI Architect Review)

| Finding | Status | Implementation |
|---------|--------|----------------|
| No query sanitization | **Resolved** | `sanitize_query()` via `_SOLR_SPECIAL_CHARS` regex |
| No filtering/faceting | **Resolved** | `fq` params + `FacetCounts` in response |
| Context has no source URLs | **Resolved** | `Source: /url_slug` appended to each context entry |
| Context has no document kind | **Resolved** | Document kind, product, version in context header |
| MCP tool too simple | **Resolved** | `product` and `max_results` parameters added |

### From Plan 5 (Vibe Code Audit)

| Finding (Must-Fix) | Status |
|---------------------|--------|
| Query injection | **Resolved** |
| Connection pooling | **Resolved** |
| Health check | **Resolved** |
| `<em>` tag mismatch | **Resolved** |
| Missing facets | **Resolved** |
| Config validation | **Resolved** |
| Stale docs cleanup | **Resolved** |

### From Architecture Review (RHOKP Product Alignment)

| Finding | Status | Implementation |
|---------|--------|----------------|
| No CVE/errata field capture | **Resolved** | `severity`, `advisory_type`, `synopsis` in `OKPDocument` |
| No `portal_content_subtype` facet | **Resolved** | `content_subtypes` in `FacetCounts` |
| No `/select-errata` support | **Resolved** | Configurable `solr_handler` via `OKPConfig` |
| Content-type-unaware context | **Resolved** | `_build_context()` includes severity, uses synopsis for advisories |
| No User-Agent header | **Resolved** | `rhokp-agent/<version>` sent on all requests |
| MCP server outside package | **Resolved** | Moved to `src/rhokp/mcp/`; `rhokp-mcp` entry point |
| No air-gap deployment guidance | **Resolved** | `docs/air-gap-deployment.md` |
| No telemetry documentation | **Resolved** | `docs/telemetry.md` |
| No health check on client | **Resolved** | `OKPClient.check_health()` method |
| Solr path not configurable | **Resolved** | `RHOKP_SOLR_HANDLER` env var / `solr_handler` config |
| Container base image unpinned | **Resolved** | Pinned to specific UBI 9 version |
| No HEALTHCHECK instruction | **Resolved** | Added to MCP server Dockerfile |

---

## Current scorecard (post v0.5.0)

| Area | v0.3.0 | v0.4.0 | v0.5.0 | Notes |
|------|--------|--------|--------|-------|
| Security (query injection) | Fail | Pass | Pass | `sanitize_query()` |
| Connection management | Fail | Pass | Pass | `OKPClient` with pooling |
| Configuration | Needs Work | Pass | Pass | `OKPConfig` frozen dataclass |
| Solr API alignment | Fail | Pass | Pass | Uses OKP defaults, correct tags |
| RHOKP content model | -- | Needs Work | Pass | CVE/errata fields, content-aware context |
| Air-gap viability | -- | Needs Work | Pass | Documented, no external runtime deps |
| Telemetry awareness | -- | Fail | Pass | User-Agent header, telemetry docs |
| MCP server packaging | -- | Fail | Pass | In-package, entry point, HEALTHCHECK |
| Container hardening | Needs Work | Needs Work | Pass | Pinned base, HEALTHCHECK |
| Feature completeness | Fail | Needs Work | Needs Work | No caching, no reranking, no evaluation |
| Observability | Fail | Needs Work | Needs Work | OTel optional, no structured logging yet |
| Resilience | Fail | Needs Work | Needs Work | No circuit breaker, basic retry only |
| Test coverage | Needs Work | Pass | Pass | 118 tests, edge cases, defensive parsing |
| API design | Pass | Pass | Pass | Clean, typed, backward-compatible |
| Documentation | Needs Work | Pass | Pass | Air-gap, telemetry, architecture |

**Summary:** 11 Pass, 3 Needs Work, 0 Fail (was 6 Fail, 6 Needs Work, 2 Pass in v0.3.0)

---

## What remains

### Priority 1: Should address

| Item | Area | Effort | Description |
|------|------|--------|-------------|
| Structured logging | Observability | 1 day | JSON-formatted logging for production aggregation |
| Response caching | Resilience | 1-2 days | TTL-based cache for identical queries |
| Circuit breaker | Resilience | 1-2 days | Open after N failures, half-open after cooldown |
| Exponential backoff | Resilience | 0.5 day | Application-level retry with backoff |
| Token-budget context | Feature | 1-2 days | Truncate context to fit LLM window |

### Priority 2: Nice to have

| Item | Area | Effort | Description |
|------|------|--------|-------------|
| SearchBackend protocol | Architecture | 2-3 days | Abstract over Solr for extensibility |
| Cross-encoder reranking | AI Quality | 2-3 days | Optional reranking for better RAG |
| Retrieval evaluation dataset | AI Quality | 2-3 days | Measure Precision@K, MRR |
| ADK adapter | Integration | 1-2 days | Google ADK framework support |
| PyPI publication | Distribution | 0.5 day | `pip install rhokp` without git clone |
| Container image scanning in CI | Security | 0.5 day | Trivy or Grype |
| Query preprocessing (synonyms) | AI Quality | 2-3 days | Red Hat term expansion |

**Estimated effort for Priority 1: 1 week. Priority 2: 2-3 weeks.**

---

## Architecture summary (v0.5.0)

```
src/rhokp/
├── __init__.py         Public API (retrieve, aretrieve, OKPClient, OKPConfig, models)
├── __main__.py         CLI: rhokp "query" --product "X" --kind documentation
├── py.typed            PEP 561 marker
├── config.py           OKPConfig (frozen, validated, env-based, configurable handler)
├── client.py           OKPClient (pooled, sync+async, User-Agent, health check)
├── models.py           OKPDocument (CVE fields), FacetCounts (subtypes), exceptions
├── retrievers.py       OKPLangChainRetriever (metadata, async, callbacks)
├── retrieve.py         Deprecated shim for backward compat
└── mcp/
    ├── __init__.py
    └── server.py       FastMCP server: search_red_hat_docs, check_okp_health
```

Entry points:
- `rhokp` -- CLI search tool
- `rhokp-mcp` -- MCP server

Container images:
- `rhokp-mcp` -- MCP server (UBI 9, pinned, HEALTHCHECK)
- `rhokp-demo` -- Reference client (UBI 9, pinned)
