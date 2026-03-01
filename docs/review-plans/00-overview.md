# Codebase Review: Five Perspectives on Production Readiness

> **Historical snapshot.** This review was conducted against v0.3.0 before the
> v0.4.0 rewrite. Many critical findings (query injection, no connection pooling,
> no health check, `<em>` vs `<b>` tag mismatch, missing facets/fields) have been
> addressed in v0.4.0. Retained for reference and to track remaining items.

**Project:** rhokp-agent v0.3.0
**Date:** 2026-02-28
**Scope:** Full codebase -- every Python file, test, doc, config, and container artifact

---

## Why five plans?

A single review catches what that reviewer knows to look for. Five perspectives cover the full surface area:

| # | Plan | Perspective | Core question | Verdict |
|---|------|-------------|---------------|---------|
| 1 | [Expert Code Review](01-expert-code-review.md) | Senior engineer | Is the code correct, robust, and maintainable? | Refactor (most components) |
| 2 | [Product Manager Review](02-product-manager-review.md) | Product manager | Does this solve a real problem for defined users? | Reframe product, extend features |
| 3 | [Software Architect Review](03-software-architect-review.md) | Systems architect | Is the architecture sound for production operation? | Refactor structure, add resilience |
| 4 | [AI Architect Review](04-ai-architect-review.md) | AI / ML engineer | Is the retrieval pipeline effective for RAG? | Harden keyword, add reranking + evaluation |
| 5 | [Vibe Code Audit](05-vibe-code-audit.md) | Production auditor | What was vibe-coded and what must change? | 9 must-fix, 12 should-fix, 12 nice-to-have |

---

## Cross-cutting findings

These issues appear in multiple plans and represent the most important gaps:

### 1. Security: Solr query injection (Plans 1, 4, 5)

User query input is passed directly to Solr with no sanitization. Special characters can manipulate the query or access unintended data. This is the single highest-priority fix.

### 2. No connection pooling (Plans 1, 3, 5)

Every `retrieve()` call creates and destroys an httpx client and TCP connection. Under production load, this causes connection exhaustion and unnecessary latency. An `OKPClient` class with persistent connections is needed.

### 3. No health check (Plans 1, 2, 3, 5)

The MCP server has no health endpoint. Container orchestrators cannot determine service readiness. This blocks any Kubernetes/Podman deployment.

### 4. Context construction is too simplistic (Plans 4, 5)

The numbered-list context format has no source citations, no document kind indicators, no deduplication, and no token-budget awareness. The LLM cannot cite sources and may receive too much or too little context.

### 5. "Demo" framing throughout the codebase (Plans 2, 5)

The `demo/` directory, container names, README, and docs all use the word "demo." This signals non-production status and must be renamed/reframed.

### 6. Stale documentation (Plans 2, 5)

6-7 of 17 markdown docs are AI-generated planning artifacts that are either stale or no longer needed. They must be removed or archived.

---

## Consolidated scorecard

| Area | Plan 1 | Plan 2 | Plan 3 | Plan 4 | Plan 5 | Overall |
|------|--------|--------|--------|--------|--------|---------|
| Security | Fail | -- | -- | -- | Fail | **Fail** |
| Correctness | Needs Work | -- | -- | -- | -- | **Needs Work** |
| Robustness / Resilience | Fail | -- | Fail | -- | Fail | **Fail** |
| Performance | Needs Work | -- | -- | -- | Needs Work | **Needs Work** |
| Feature completeness | -- | Fail | -- | -- | -- | **Fail** |
| User onboarding | -- | Fail | -- | -- | -- | **Fail** |
| Retrieval quality | -- | -- | -- | Needs Work | -- | **Needs Work** |
| Context for LLM | -- | -- | -- | Fail | -- | **Fail** |
| Architecture / Extensibility | -- | -- | Needs Work | -- | -- | **Needs Work** |
| Observability | Needs Work | Fail | Fail | -- | -- | **Fail** |
| Test coverage | Needs Work | -- | -- | Fail | Needs Work | **Needs Work** |
| Documentation | -- | Needs Work | -- | -- | Needs Work | **Needs Work** |
| Packaging | -- | -- | Needs Work | -- | Needs Work | **Needs Work** |
| Code quality / style | Pass | -- | Pass | -- | Pass | **Pass** |
| API design | -- | -- | Pass | -- | -- | **Pass** |

**Summary:** 6 Fail, 6 Needs Work, 2 Pass.

---

## Consolidated effort estimate

| Phase | Items | Effort | Focus |
|-------|-------|--------|-------|
| Must Fix | 9 items from Vibe Audit | 3-4 days | Security, connection pooling, health check, naming, docs |
| Should Fix | 12 items from Vibe Audit | 5-6 days | Config, logging, retry, context, tests, TLS, packaging |
| Architecture | Structure changes from Architect Review | 5-7 days | OKPClient, SearchBackend, MCP in package, config module |
| AI Pipeline | Retrieval improvements from AI Review | 5-7 days | Query preprocessing, filtering, context builder, evaluation |
| Nice to Have | 12 items from Vibe Audit | 10-12 days | Circuit breaker, caching, reranking, metrics, PyPI |

**Total estimated effort: 4-6 weeks of focused work to reach production grade.**

---

## Recommended execution order

**Week 1:** Must Fix (security, connection pooling, health check, stale docs, rename demo)

**Week 2:** Should Fix part 1 (config object, structured logging, timeout hierarchy, retry)

**Week 3:** Should Fix part 2 (context builder, tests, TLS, MCP packaging) + Architecture foundations (OKPClient, models extraction)

**Week 4:** AI Pipeline (query sanitization via edismax, filtering, evaluation dataset)

**Weeks 5-6:** Nice to Have (circuit breaker, caching, reranking, metrics, containers, PyPI)

---

## What to keep vs. what to rewrite

| Component | Verdict | Rationale |
|-----------|---------|-----------|
| Core retrieval logic (`retrieve.py`) | **Refactor** | Logic is correct; needs `OKPClient` wrapper, defensive parsing, input sanitization |
| Data models (`OKPDocument`, `RetrieveResult`) | **Keep** | Well-designed frozen dataclasses |
| Exception hierarchy | **Refactor** | Add `OKPResponseError`; fix taxonomy |
| LangChain adapter (`retrievers.py`) | **Refactor** | Add callbacks, search_kwargs, proper async |
| MCP server (`server.py`) | **Refactor** | Add health check, structured response, move into package |
| Reference client (`demo/ask_okp.py`) | **Rewrite** | SystemExit error handling, brittle response parsing, hardcoded defaults |
| Context construction (`_build_context`) | **Rewrite** | Too simplistic; needs citations, token awareness, deduplication |
| Tests | **Extend significantly** | Happy path covered; edge cases, integration, load all missing |
| CI pipeline | **Extend** | Add image scanning, integration tests, release automation |
| Containers | **Harden** | Add HEALTHCHECK, pin versions, consider multi-stage |
| Documentation (user-facing) | **Improve** | Add API reference, deployment guide, configuration reference |
| Documentation (planning artifacts) | **Remove/Archive** | 6-7 stale AI-generated plans that no longer serve a purpose |
