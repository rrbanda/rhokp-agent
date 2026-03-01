# Plan 2: Product Manager Review

**Perspective:** Product manager evaluating market readiness, user experience, and adoption potential
**Core question:** Does this solve a real problem, and is it ready for users to depend on in production?
**Scope:** Feature set, documentation, user journeys, versioning, competitive positioning
**Date:** 2026-02-28

---

## 1. Product Definition Assessment

### 1.1 What is this product?

**Stated:** "Red Hat Offline Knowledge Portal retrieval for RAG and AI agents."

**Actual:** A Python library that wraps OKP's Solr search API and exposes it through three interfaces (Python API, LangChain retriever, MCP tool), plus a script that connects OKP retrieval to Llama Stack's LLM API.

### 1.2 Who is the user?

**Not stated.** The README and docs never define the target user. Candidates:

| User persona | What they need | Current fit |
|--------------|---------------|-------------|
| Red Hat field engineer building an internal chatbot | Quick setup, reliable retrieval, LLM integration | Partial -- retrieval works, LLM integration is fragile |
| Partner building a product on top of OKP | Stable API, versioned releases, SLA-grade reliability | Poor -- no connection pooling, no caching, no circuit breaker |
| Community developer experimenting with OKP + AI | Easy install, works out of the box, clear examples | Poor -- requires OKP instance (Red Hat subscription), no mock mode |
| Platform team deploying OKP search as a service | Container images, health checks, monitoring, scaling | Poor -- no health endpoints, no structured logging, no metrics |

**Verdict: Needs Work.** The product has no defined persona, no user stories, and no success criteria. This must be decided before any further development.

### 1.3 Value proposition vs. alternatives

What does rhokp-agent offer that `curl http://okp:8080/solr/portal/select?q=...` does not?

| Value-add | Strength |
|-----------|----------|
| Typed Python dataclasses (`OKPDocument`, `RetrieveResult`) | Moderate -- saves parsing effort |
| HTML tag stripping from Solr highlights | Low -- a few lines of code |
| LangChain `BaseRetriever` integration | High -- plugs into the dominant RAG framework |
| MCP tool for AI agents | High -- enables agentic OKP search |
| Sync + async support | Moderate -- convenience |
| OTel tracing (optional) | Low -- minimal span attributes |
| Error hierarchy (`OKPError`, `OKPConnectionError`, `OKPSearchError`) | Moderate -- better than raw httpx errors |

**Verdict: The value is real but narrow.** The LangChain and MCP integrations are the strongest differentiators. The core retrieval is a thin wrapper. For adoption, the product needs to offer more than what a competent engineer could write in an afternoon.

---

## 2. Feature Completeness

### 2.1 What production retrieval tools offer (and this does not)

| Feature | Industry standard | rhokp-agent | Gap severity |
|---------|------------------|-------------|--------------|
| Keyword search | Yes | Yes | -- |
| Semantic / vector search | Yes (hybrid) | No | High |
| Filtering by product, version, doc type | Yes | No | High |
| Pagination | Yes | No (returns top N only) | Medium |
| Caching (response-level) | Yes | No | High |
| Result scoring / confidence | Yes | No | Medium |
| Query suggestion / autocomplete | Common | No | Low |
| Faceted results | Common | No | Low |
| Document-level vs. chunk-level retrieval | Yes | No (chunk only, via Solr highlighting) | Medium |
| Token-budget-aware context construction | Yes (production RAG) | No | High |
| Source citation URLs | Yes | Partial (url_slug exists but not used in context) | Medium |
| Rate limiting / throttling | Yes | No | Medium |
| Retry with exponential backoff | Yes | Transport-level only | Medium |
| Health check endpoint | Yes | No | High |
| Structured error responses | Yes | No (MCP returns plain strings) | Medium |

**Verdict: Fail.** The feature set is appropriate for a prototype, not a production tool. The most critical gaps are: no filtering, no caching, no health check, and no token-budget awareness.

### 2.2 What exists and works

| Feature | Status | Quality |
|---------|--------|---------|
| `retrieve()` / `aretrieve()` | Working | Good API design, clean code |
| `OKPLangChainRetriever` | Working | Functional but limited (no callbacks, no search_kwargs) |
| MCP `search_red_hat_docs` tool | Working | Functional but no health check, returns strings |
| CLI (`python -m rhokp`) | Working | Minimal but correct |
| CI (lint, test, container build) | Working | Solid; multi-Python matrix |
| Container images (UBI 9) | Working | Builds and runs; non-root |

---

## 3. User Journey Analysis

### 3.1 Journey: "I want to search OKP from Python"

| Step | Experience | Friction |
|------|-----------|----------|
| 1. Find the project | Discover via GitHub / internal link | None |
| 2. Read README | Clear feature list, quick start section | Must know what OKP is; no explanation for newcomers |
| 3. Install | `pip install -e .` | Works; but no PyPI package yet |
| 4. Run OKP | `podman run ...` with ACCESS_KEY | **High friction.** Requires Red Hat registry access, valid ACCESS_KEY, understanding of Podman. No mock/local alternative. |
| 5. First query | `rhokp "install OpenShift"` | Works if OKP is running; cryptic error if not |
| 6. Use in Python | `from rhokp import retrieve` | Clean; good type hints |
| 7. Integrate with LangChain | `from rhokp.retrievers import OKPLangChainRetriever` | Works; example in README |
| 8. Debug issues | Read logs | Basic logging only; no structured output |

**Biggest friction:** Step 4. A user cannot try this product without a running OKP instance. There is no mock mode, no test fixture, no sandbox OKP. This is a major adoption barrier.

### 3.2 Journey: "I want to deploy the MCP server"

| Step | Experience | Friction |
|------|-----------|----------|
| 1. Build container | `podman build -f containers/mcp-server/Dockerfile .` | Requires Red Hat registry access for base image |
| 2. Run container | `podman run -e RHOKP_BASE_URL=... -p 8010:8010 rhokp-mcp` | Works |
| 3. Register with Llama Stack | Follow `mcp_server/README.md` | Instructions exist but are sparse |
| 4. Monitor health | -- | **Not possible.** No health endpoint. |
| 5. Scale | -- | Stateless HTTP is good for scaling, but no guidance |
| 6. Debug issues | Container logs | Unstructured text logs |

**Biggest gap:** No observability. A production deployment has no way to know if the service is healthy, how long queries take, or what errors are occurring.

### 3.3 Journey: "I want to use OKP + LLM to answer questions"

| Step | Experience | Friction |
|------|-----------|----------|
| 1. Set environment | `LLAMA_STACK_BASE`, `RHOKP_BASE_URL`, `MODEL` | Three separate env vars; no validation |
| 2. Run | `python demo/ask_okp.py "question"` | **Called "demo" -- signals non-production** |
| 3. Get answer | Prints LLM response | Works if everything is configured correctly |
| 4. Handle errors | `SystemExit` with error message | Crashes the process; non-recoverable |
| 5. Customize | Change model, add tools | Hardcoded `gemini/models/gemini-2.5-flash` default; limited `web_search` tool |

**Biggest problem:** This is labeled "demo" but is the only way to use OKP + LLM end-to-end. It must be promoted to a proper application with production error handling.

---

## 4. Documentation Assessment

### 4.1 Documentation inventory

| Document | Type | Audience | Quality | Should keep? |
|----------|------|----------|---------|-------------|
| `README.md` | User-facing | All users | Good structure, needs persona clarity | Yes -- improve |
| `CHANGELOG.md` | User-facing | All users | Stale (stops at 0.2.0, version is 0.3.0) | Yes -- update |
| `CONTRIBUTING.md` | Contributor-facing | Contributors | Basic but sufficient | Yes |
| `SECURITY.md` | Contributor-facing | Security reporters | Minimal | Yes -- expand |
| `LICENSE` | Legal | All | Correct (Apache-2.0) | Yes |
| `docs/architecture.md` | Internal | Developers | Good overview diagram | Yes |
| `docs/running.md` | User-facing | Operators | Useful | Yes |
| `docs/containers-step-by-step.md` | User-facing | Operators | Useful | Yes |
| `mcp_server/README.md` | User-facing | MCP users | Useful but sparse | Yes -- expand |
| `demo/README.md` | User-facing | -- | Labels itself "demo" | Rewrite as production client docs |
| `containers/README.md` | User-facing | Operators | Useful | Yes |
| `docs/oss-roadmap.md` | Internal/AI-generated | Internal | **Stale** -- says "No tests", "No CI" | Remove or archive |
| `docs/retriever-recommendation.md` | Internal/AI-generated | Internal | Decision doc; useful historically | Move to wiki/archive |
| `docs/retriever-implementation-plan.md` | Internal/AI-generated | Internal | Implementation plan; now executed | Remove or archive |
| `docs/codebase-understanding-plan.md` | Internal/AI-generated | Internal | Planning artifact | Remove |
| `docs/podman-ubi-plan.md` | Internal/AI-generated | Internal | Planning artifact | Remove |
| `docs/public-repo-checklist.md` | Internal | Internal | Compliance checklist | Move to wiki/archive |
| `PLAN.md` | Internal/AI-generated | Internal | General plan; superseded | Remove |

**Verdict: Documentation bloat.** 7 of 17 documents are AI-generated internal planning artifacts that are either stale or no longer needed. They create noise for external contributors and a false sense of project maturity. A production project should have: user docs, contributor docs, and API reference. Internal planning belongs in a wiki or issue tracker, not the repo.

### 4.2 Missing documentation

| Document needed | Purpose | Priority |
|-----------------|---------|----------|
| API reference (`docs/api.md`) | Complete public API docs with all parameters, return types, exceptions | High |
| Deployment guide (`docs/deployment.md`) | Production deployment with health checks, monitoring, scaling | High |
| Configuration reference | All env vars, defaults, validation rules | High |
| Troubleshooting guide | Common errors and fixes | Medium |
| Security considerations | Input sanitization, TLS, auth, data handling | High |
| Compatibility matrix | OKP versions, Python versions, LangChain versions tested | Medium |

---

## 5. Versioning and Release Process

### 5.1 Current state

- Version: 0.3.0 in `pyproject.toml` and `__init__.py`
- CHANGELOG: Documents up to 0.2.0 only
- No git tags for releases
- No GitHub Releases
- No PyPI publication
- No container image versioning strategy

**Verdict: Fail.** Version 0.3.0 exists but has no corresponding changelog entry, no tag, and no release. Users have no way to know what changed or pin to a stable version.

### 5.2 What production requires

- Every version bump must have a CHANGELOG entry BEFORE the bump
- Every release must be tagged (`v0.3.0`) and have a GitHub Release
- Container images must be tagged with the version (not just `latest`)
- Consider publishing to PyPI for `pip install rhokp` to work without git clone
- Pin major dependency versions and document compatibility

---

## 6. Product Readiness Scorecard

| Category | Rating | Key gap |
|----------|--------|---------|
| Problem-solution fit | Needs Work | Value is real but narrow; must differentiate beyond a thin Solr wrapper |
| Target user definition | Fail | No defined persona, no user stories |
| Feature completeness | Fail | No filtering, caching, health checks, token awareness |
| User onboarding | Fail | Cannot try without OKP instance; no mock mode |
| Documentation | Needs Work | Good structure but stale/bloated; missing API reference and deployment guide |
| Versioning / releases | Fail | 0.3.0 undocumented; no tags, no PyPI, no container versioning |
| Error experience | Needs Work | Cryptic errors; SystemExit in client code |
| Observability | Fail | No health check, no metrics, no structured logging |
| Competitive positioning | Needs Work | LangChain + MCP integration is strong; everything else is thin |

---

## 7. Recommended User Stories (Prioritized)

### P0 -- Must have for production

1. **As a platform engineer, I need a health check endpoint** so I can configure Kubernetes liveness/readiness probes for the MCP server.
2. **As a developer, I need to filter results by product and version** so I get relevant docs, not everything OKP has indexed.
3. **As an operator, I need structured logging** so I can aggregate and alert on errors in production.
4. **As a user, I need clear error messages** when OKP is unreachable, misconfigured, or returns unexpected data.
5. **As a consumer, I need a published changelog for every version** so I know what changed and whether to upgrade.

### P1 -- Should have

6. **As a RAG developer, I need token-budget-aware context construction** so the context fits within my LLM's context window.
7. **As a developer, I need a mock/sandbox mode** so I can develop and test without a running OKP instance.
8. **As an architect, I need response caching** so repeated queries don't hit OKP unnecessarily.
9. **As a LangChain user, I need callback/tracing support** so I can debug retrieval in LangSmith.
10. **As a user, I need the reference client to be production-grade** (not labeled "demo") with proper error handling and configurable defaults.

### P2 -- Nice to have

11. **As a user, I need source citation URLs in the context** so the LLM can cite sources.
12. **As a power user, I need pagination** to browse large result sets.
13. **As an advanced user, I need query preprocessing** (synonym expansion, natural-language-to-keyword rewriting) for better retrieval.
14. **As an operator, I need container images tagged with version numbers** for reproducible deployments.

---

## Verdict: Refactor or Rewrite?

**Product framing:** Reframe from scratch. Define the persona, write user stories, and cut the scope to what matters for the first production user.

**Core library (`retrieve.py`):** Keep and extend. The API design is sound. Add filtering, caching, and connection pooling.

**LangChain adapter:** Keep and improve. Add callbacks and search_kwargs.

**MCP server:** Keep and harden. Add health check, structured responses, startup validation.

**Reference client (`demo/ask_okp.py`):** Rewrite as a proper CLI command or remove from the core distribution. It cannot ship as production code in its current state.

**Documentation:** Triage aggressively. Remove stale planning docs. Write the missing production docs (API reference, deployment guide, configuration reference).

**Versioning:** Fix immediately. Document 0.3.0 changes, tag the release, establish a release process.
