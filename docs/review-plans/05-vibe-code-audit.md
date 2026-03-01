# Plan 5: Vibe Code Audit

**Perspective:** Production readiness auditor identifying AI-generated code patterns that need hardening
**Core question:** What was "vibe-coded" and what must change before this system handles real traffic?
**Scope:** All code, tests, docs, configuration, CI/CD, containers
**Date:** 2026-02-28

---

## What is a vibe code audit?

"Vibe coding" is the practice of generating code rapidly -- often with AI assistance -- that looks correct, follows patterns, and passes basic tests, but was never subjected to the scrutiny that production systems require. Vibe code has these characteristics:

- **Looks professional** -- Clean formatting, consistent style, proper naming
- **Works in the happy path** -- The main use case functions correctly
- **Has tests that pass** -- But only for the happy path
- **Has documentation** -- But some of it is aspirational, stale, or generated alongside the code
- **Lacks edge-case hardening** -- Because edge cases were never encountered during generation
- **Lacks operational features** -- Because the generator focused on functionality, not operability
- **Has unexplained magic numbers** -- Because values were chosen by "seems right" rather than measurement

This audit examines every artifact in the repository for vibe-coding indicators and prescribes production-grade remediation.

---

## 1. Evidence of Vibe Coding

### 1.1 Documentation outnumbers source code

| Category | Lines | Files |
|----------|-------|-------|
| Python source (src/ + mcp_server/ + demo/) | ~640 | 7 |
| Python tests | ~568 | 5 |
| Markdown documentation | ~2,000+ | 17 |
| **Ratio of docs to source** | **3:1** | **2.4:1** |

A 3:1 docs-to-source ratio is unusual. It indicates a "plan first, generate code, generate tests, generate docs" workflow where each generation step produced polished output, but the artifacts were never critically reviewed as a whole.

**Specific evidence:**
- `docs/oss-roadmap.md` (149 lines) is a thorough plan that lists "No tests" and "No CI" as gaps -- but tests and CI now exist. The doc was generated, executed against, and never updated.
- `docs/retriever-recommendation.md` (84 lines) is a well-structured analysis of retriever options that reads as a one-shot LLM output: comprehensive, balanced, with a "Summary table" and "Suggested next steps."
- `docs/retriever-implementation-plan.md` (128 lines) is a detailed implementation checklist that was executed and then left in the repo alongside the implemented code.
- `docs/codebase-understanding-plan.md` (131 lines) is a plan to understand the codebase -- a meta-document that serves no user.
- `docs/podman-ubi-plan.md` (261 lines) is the longest document in the project, longer than most source files.
- `PLAN.md` (92 lines) at the repo root is a general project plan.

**Verdict:** 6-7 of the 17 documents are AI-generated planning artifacts that should not be in a production repository. They create a false sense of maturity and confuse contributors.

### 1.2 Stale documentation

| Document | Stale claim | Actual state |
|----------|------------|--------------|
| `docs/oss-roadmap.md` | "No tests" (P0 gap) | Tests exist: 568 lines, 5 files |
| `docs/oss-roadmap.md` | "No CI" (P0 gap) | CI exists: `.github/workflows/ci.yml`, 4 jobs |
| `docs/oss-roadmap.md` | "MCP server mutates `sys.path`; fragile" | Fixed: MCP server now uses `from rhokp import ...` |
| `docs/oss-roadmap.md` | "Demo script relies on `sys.path` hack" | Fixed: demo now uses `from rhokp import ...` |
| `docs/oss-roadmap.md` | "Return type is a loose `dict`" | Fixed: now uses typed dataclasses |
| `CHANGELOG.md` | Documents up to 0.2.0 | Version is 0.3.0 |
| `docs/retriever-implementation-plan.md` | Lists tasks as unchecked | Tasks were completed |

**Verdict:** Documentation was generated at a point in time and never revisited. This is a hallmark of vibe coding: generate, ship, move on.

### 1.3 Perfectly uniform code structure

Every Python file in the project follows the same structure:

```
"""Module docstring with usage example."""

from __future__ import annotations

import stdlib_modules
import third_party_modules
from internal import modules

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / section headers
# ---------------------------------------------------------------------------

# Helper functions (private, underscore-prefixed)

# Public API
```

Tests follow the same pattern:
```
"""Test docstring with requirements note."""

from __future__ import annotations

import pytest
from unittest.mock import patch

# Constants (test fixtures at module level)

# Test classes with descriptive names
```

This consistency is a strength for readability. But the **perfect uniformity across all files** -- the exact same section header style, the exact same import ordering convention, the exact same docstring structure -- indicates single-author AI generation rather than organic development.

**Verdict:** Low risk. The consistency is genuinely helpful. The concern is that all files were generated together rather than evolved through real use, which means no file has been battle-tested.

### 1.4 Magic numbers without rationale

| Value | Location | Chosen because... |
|-------|----------|-------------------|
| `_DEFAULT_TIMEOUT = 30.0` | `retrieve.py:42` | ? |
| `_DEFAULT_RETRIES = 2` | `retrieve.py:43` | ? |
| `hl.snippets = 2` | `retrieve.py:140` | ? (only 1 is used) |
| `hl.fragsize = 300` | `retrieve.py:141` | ? |
| `snippet[:500]` | `retrieve.py:162` | ? |
| `_DEFAULT_ROWS = 5` | `retrieve.py:41` | ? |
| `timeout=120.0` | `demo/ask_okp.py:61` | ? |
| `rows=5` | `demo/ask_okp.py:108` | Duplicates _DEFAULT_ROWS |

None of these values have documented rationale. In a production system, every timeout, retry count, and buffer size should be explained:
- "30s timeout because OKP cold-start takes up to 20s"
- "2 retries because network blips resolve within 3 attempts in our environment"
- "300-char fragment size because Red Hat doc paragraphs average 250 chars"

Without rationale, we cannot assess whether these values are correct, conservative, or dangerous.

**Verdict:** Medium risk. The values are probably fine for low-traffic use, but under production load, untuned timeouts and buffer sizes cause cascading failures.

### 1.5 Tests cover the happy path and obvious errors

The test suite is well-structured and covers:

| Test category | Coverage | Quality |
|--------------|----------|---------|
| Successful retrieval (sync) | 7 tests | Good |
| Successful retrieval (async) | 1 test | Minimal |
| HTTP errors (4xx/5xx) | 2 tests | Good |
| Connection errors | 2 tests | Good |
| Timeout errors | 1 test | Good |
| Input validation (empty query, invalid rows) | 3 tests | Good |
| Serialization (to_dict) | 1 test | Good |
| Env var fallback | 2 tests | Good |
| LangChain retriever | 6 tests | Good |
| MCP server tool | 5 tests | Good |
| CLI | 4 tests | Good |
| HTML stripping | 4 tests | Good |

What is NOT tested:

| Gap | Risk | Impact if hit in production |
|-----|------|-----------------------------|
| Malformed Solr JSON (missing keys, wrong types) | High | Unhandled TypeError/KeyError crashes the process |
| Unicode in titles/snippets | Medium | Mojibake or encoding errors in LLM prompts |
| Very large responses (1000+ docs) | Medium | Memory exhaustion, slow context construction |
| Concurrent calls to `retrieve()` | High | Unknown thread safety behavior |
| OTel span creation and attributes | Low | Silent failure of observability |
| Env var with invalid values (e.g., RHOKP_RAG_ROWS="abc") | Medium | Unhandled ValueError |
| Network-level issues (DNS failure, SSL cert error) | Medium | Unclear error messages |
| Solr special characters in query | Critical | Solr injection or query parse failure |
| `_parse_response` with partial highlighting | Medium | Missing or wrong snippets |

**Verdict:** The test suite was generated to cover the obvious cases. The edge cases that production traffic exposes were never tested because they were never encountered during generation.

### 1.6 No security hardening

| Security concern | Current state | Production requirement |
|-----------------|--------------|----------------------|
| Solr query injection | No sanitization | Escape special characters; use parameterized queries |
| TLS verification | Default (verify=True) | Configurable; support custom CA bundles |
| Authentication to OKP | Not supported | Support auth headers (bearer token, basic auth) |
| Input length limits | No maximum query length | Prevent DoS via extremely long queries |
| Response size limits | No maximum response size | Prevent OOM from enormous Solr responses |
| CORS on MCP server | Not configured | Restrict origins in production |
| Secrets in logs | Query logged in plain text | PII in queries could be logged |

**Verdict:** No security review was performed. This is consistent with vibe coding, where functionality is the focus and security is deferred.

### 1.7 No performance baseline

There are no benchmarks, no load tests, no profiling results. Specific unknowns:

- How long does `retrieve()` take with a real OKP instance? (latency)
- How many concurrent `retrieve()` calls can one process handle? (throughput)
- How much memory does the MCP server use under load? (resource consumption)
- What happens when OKP is slow (5s response time) and requests pile up? (backpressure)
- What is the connection overhead of creating/destroying httpx clients per call? (connection cost)

**Verdict:** "It works on my machine" is the current validation level. Production systems need measured performance baselines and load tests.

---

## 2. Production-Grade Remediation Plan

### 2.1 Must Fix (blocks production deployment)

These items must be resolved before the system handles real user traffic.

| # | Item | File(s) | Effort | Risk if not fixed |
|---|------|---------|--------|-------------------|
| M1 | **Solr query injection** -- Sanitize query input by escaping Solr special characters (`+ - && \|\| ! ( ) { } [ ] ^ " ~ * ? : \`) | `retrieve.py` | 2 hours | Unauthorized data access, query manipulation |
| M2 | **Connection pooling** -- Create `OKPClient` class with persistent httpx client; stop creating/destroying TCP connections per call | `retrieve.py`, `mcp_server/server.py`, `retrievers.py` | 1 day | Performance degradation under load |
| M3 | **Defensive response parsing** -- Validate Solr response structure before accessing fields; handle unexpected shapes gracefully | `retrieve.py` | 4 hours | Unhandled crashes from malformed responses |
| M4 | **Health check endpoint** -- Add `/health` to MCP server that verifies OKP reachability | `mcp_server/server.py` | 2 hours | No way to monitor service health in production |
| M5 | **Error taxonomy fix** -- Introduce `OKPResponseError` for non-connection errors (bad JSON, unexpected content type); stop wrapping everything in `OKPConnectionError` | `retrieve.py` | 2 hours | Incorrect retry/alerting decisions |
| M6 | **Input length limit** -- Add maximum query length (e.g., 10,000 chars) to prevent DoS | `retrieve.py` | 1 hour | Memory/CPU exhaustion from malicious queries |
| M7 | **Response size limit** -- Cap rows at a sane maximum (e.g., 100); add response size validation | `retrieve.py` | 1 hour | Memory exhaustion from huge Solr responses |
| M8 | **Rename `demo/`** -- Rename to `examples/` or promote to package CLI command; update all references | All | 2 hours | Signals "not production" to users and evaluators |
| M9 | **Fix stale docs** -- Remove or archive `docs/oss-roadmap.md`, `docs/retriever-implementation-plan.md`, `docs/codebase-understanding-plan.md`, `PLAN.md`; update `CHANGELOG.md` for 0.3.0 | `docs/`, root | 2 hours | Misleading information for users and contributors |

**Estimated total: 3-4 days**

### 2.2 Should Fix (creates risk in production)

These items create risk under real-world conditions and should be addressed in the first production iteration.

| # | Item | File(s) | Effort | Risk if not fixed |
|---|------|---------|--------|-------------------|
| S1 | **Configuration object** -- Create `OKPConfig` dataclass; validate at startup, not per-call; log config on startup | New `config.py` | 4 hours | Invalid config only discovered at runtime |
| S2 | **Structured logging** -- Switch to JSON-formatted structured logs; add request-id propagation | All Python files | 1 day | Cannot aggregate or alert on logs in production |
| S3 | **Timeout hierarchy** -- Use httpx `Timeout(connect=5.0, read=25.0, pool=10.0)` instead of flat 30s | `retrieve.py` | 2 hours | Slow connects block reads; pool exhaustion is invisible |
| S4 | **Application-level retry with backoff** -- Add retry with exponential backoff for transient failures (502, 503, 504, connection reset) | `retrieve.py` | 4 hours | Transient OKP failures become permanent errors |
| S5 | **LangChain async fix** -- Use `aretrieve()` in `_aget_relevant_documents` instead of `asyncio.to_thread` wrapping sync | `retrievers.py` | 1 hour | Thread pool exhaustion under concurrent async calls |
| S6 | **Token-budget-aware context** -- Add `max_tokens` parameter to context construction; estimate token count and truncate | `retrieve.py` or new `context.py` | 4 hours | Context exceeds LLM window for large result sets |
| S7 | **Context with citations** -- Include source URLs and document kind in context string | `retrieve.py` | 2 hours | LLM cannot cite sources; users cannot verify answers |
| S8 | **MCP structured responses** -- Return JSON with `num_found`, `docs`, `context` instead of plain string | `mcp_server/server.py` | 2 hours | Agent cannot reason about result quality |
| S9 | **Edge-case tests** -- Add tests for malformed JSON, Unicode, large responses, concurrent calls, Solr special chars, invalid env vars | `tests/` | 1 day | Regressions go undetected; coverage is illusory |
| S10 | **TLS configuration** -- Add `verify` and `cert` parameters to support custom CA bundles and mTLS | `retrieve.py` | 2 hours | Cannot connect to OKP in environments with custom PKI |
| S11 | **Move MCP server into package** -- Move to `src/rhokp/mcp/`; add `rhokp-mcp` console_scripts entry point | `mcp_server/` -> `src/rhokp/mcp/` | 4 hours | Server is not installable via pip |
| S12 | **Auth header support** -- Add optional bearer token or basic auth for OKP requests | `retrieve.py` | 2 hours | Cannot connect to auth-protected OKP instances |

**Estimated total: 5-6 days**

### 2.3 Nice to Have (polish for production maturity)

These items bring the project to the level expected of a mature production open-source tool.

| # | Item | File(s) | Effort | Benefit |
|---|------|---------|--------|---------|
| N1 | **Circuit breaker** -- In-process circuit breaker (open after N failures, half-open after cooldown) | `retrieve.py` or `client.py` | 1 day | Prevents hammering a down OKP instance |
| N2 | **Response caching** -- TTL-based in-memory cache for identical queries | New `cache.py` | 1 day | Reduces OKP load; improves latency for repeated queries |
| N3 | **SearchBackend protocol** -- Abstract Solr-specific logic behind a protocol for future backend swaps | New `backends/` | 1 day | Extensibility for hybrid search |
| N4 | **Solr `edismax` parser** -- Switch to `edismax` with `qf` and `mm` for better relevance | `retrieve.py` | 4 hours | Better multi-field matching |
| N5 | **Query filtering** -- Add `filter` parameter mapping to Solr `fq` for product/version/doc-kind filtering | `retrieve.py` | 4 hours | Scoped searches improve RAG precision |
| N6 | **Reranking** -- Optional cross-encoder reranking stage | New module | 2 days | Significant quality improvement |
| N7 | **Evaluation suite** -- Evaluation dataset + retrieval quality metrics (P@K, MRR) | New `eval/` | 2 days | Measure and prevent retrieval quality regressions |
| N8 | **Prometheus metrics** -- Query count, latency histogram, error rate | `observability.py` | 1 day | Operational visibility |
| N9 | **Container hardening** -- Multi-stage builds, pinned base images, HEALTHCHECK, vulnerability scanning | `containers/` | 4 hours | Smaller, more secure, reproducible images |
| N10 | **PyPI publication** -- Publish to PyPI so `pip install rhokp` works without git clone | CI pipeline | 4 hours | Standard Python distribution |
| N11 | **Dependency lock file** -- `pip-compile` or `uv.lock` for reproducible installs | Root | 2 hours | Deterministic builds |
| N12 | **ADK adapter** -- Google Agent Development Kit retriever adapter | New `adapters/adk.py` | 1 day | Broader agent framework support |

**Estimated total: 10-12 days**

---

## 3. Prioritized Execution Order

```
Week 1: Must Fix (M1-M9)
  ├── Day 1-2: M2 (OKPClient), M5 (error taxonomy), M3 (defensive parsing)
  ├── Day 3: M1 (query sanitization), M6 (input limit), M7 (response limit)
  └── Day 4: M4 (health check), M8 (rename demo), M9 (fix stale docs)

Week 2: Should Fix (S1-S12)
  ├── Day 1: S1 (config object), S3 (timeout hierarchy), S4 (retry with backoff)
  ├── Day 2: S2 (structured logging), S5 (LangChain async fix)
  ├── Day 3: S6 (token-budget context), S7 (citations), S8 (MCP structured response)
  ├── Day 4: S9 (edge-case tests)
  └── Day 5: S10 (TLS config), S11 (MCP into package), S12 (auth header)

Week 3-4: Nice to Have (N1-N12)
  ├── N3 (SearchBackend protocol) + N4 (edismax) + N5 (filtering)
  ├── N1 (circuit breaker) + N2 (caching)
  ├── N6 (reranking) + N7 (evaluation suite)
  └── N8 (metrics) + N9 (containers) + N10 (PyPI) + N11 (lock file) + N12 (ADK)
```

---

## 4. How to Verify the Audit is Complete

After remediation, every item below should be true:

| Check | Verification |
|-------|-------------|
| No Solr injection possible | Fuzz test with Solr special characters passes |
| Connection pooling works | Load test shows connection reuse (not N connections for N queries) |
| Malformed responses handled | Tests with 10+ malformed JSON shapes all produce clear errors |
| Health check works | `curl /health` returns 200 with status JSON |
| Error types are accurate | `OKPConnectionError` only raised for transport failures |
| Structured logs produced | Logs parse as valid JSON with request-id, level, message |
| Token budget respected | Context for 50 docs does not exceed specified max_tokens |
| Stale docs removed | No document references non-existent gaps or completed plans |
| "Demo" does not appear | `grep -ri demo` returns zero results (except historical changelog) |
| All magic numbers documented | Every timeout, buffer size, and limit has a comment explaining why |
| Edge cases tested | Test suite includes malformed input, Unicode, concurrent calls, large responses |
| MCP server in package | `pip install rhokp[mcp] && rhokp-mcp` starts the server |
| Config validated at startup | Invalid env vars produce clear error before first request |

---

## 5. Summary Scorecard

| Area | Current state | After Must Fix | After Should Fix | After Nice to Have |
|------|--------------|----------------|------------------|-------------------|
| Security | Fail | Pass | Pass | Pass |
| Resilience | Fail | Needs Work | Pass | Pass |
| Performance | Needs Work | Pass | Pass | Pass |
| Observability | Fail | Needs Work | Pass | Pass |
| Test coverage | Needs Work | Needs Work | Pass | Pass |
| Code quality | Pass | Pass | Pass | Pass |
| Documentation | Needs Work | Pass | Pass | Pass |
| Packaging | Needs Work | Pass | Pass | Pass |
| Retrieval quality | Needs Work | Needs Work | Needs Work | Pass |

---

## 6. Final Verdict

This codebase is a well-structured prototype that was generated with AI assistance and follows good patterns. The code quality is genuinely above average for a project at this stage. The gap is not in the code's style or structure -- it is in the **things that were never done** because they only matter when real traffic hits:

1. **Security was never tested** (Solr injection, auth, TLS)
2. **Performance was never measured** (no benchmarks, no load tests)
3. **Edge cases were never hit** (malformed responses, concurrent access, Unicode)
4. **Operational features were never needed** (health checks, structured logs, metrics)
5. **Documentation was generated but never maintained** (stale plans, missing API reference)

The path forward is clear: keep the good structure, harden everything that touches untrusted input or production infrastructure, and delete the planning artifacts that have served their purpose. Estimated total effort for full production readiness: **4-6 weeks of focused work.**
