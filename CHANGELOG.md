# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- (None)

## [0.5.0] - 2026-02-28

### Added

- **OpenShift deployment manifests** -- Kustomize-based manifests in `deploy/openshift/` for deploying OKP, MCP server, and ADK web UI on OpenShift with Kubernetes Secrets (`envFrom`), Services, and TLS Routes.
- **Deployment documentation** -- `deploy/README.md` with instructions for both local (Podman Compose) and OpenShift (`oc apply -k`) workflows.
- **ADK container image** -- `containers/adk-agent/Dockerfile` for the Google ADK agent web UI (`quay.io/rbrhssa/rhokp-adk`).

### Changed

- **Container base images** switched from UBI 9 to `python:3.12-slim` for portability.
- **ADK web server** binds to `0.0.0.0` instead of `127.0.0.1` for container/Kubernetes compatibility.
- **`podman-compose.yaml`** updated to run all three services (OKP, MCP, ADK) by default with shared network and documented `.env` file usage.

### Removed

- **`mcp_server/` directory** -- deprecated shim removed. Use `rhokp-mcp` entry point or `python -m rhokp.mcp.server`.
- **`src/rhokp/retrieve.py`** -- deprecated backward-compat shim removed. Import from `rhokp` directly.
- **Dead planning docs** -- removed completed/superseded docs (`PLAN.md`, `docs/oss-roadmap.md`, `docs/podman-ubi-plan.md`, `docs/containers-step-by-step.md`, `docs/codebase-understanding-plan.md`, `docs/retriever-implementation-plan.md`, `docs/retriever-recommendation.md`).
- **`demo/` directory** -- replaced by the ADK agent.
- **`requirements.txt`** -- all dependencies managed via `pyproject.toml`.

## [0.4.0] - 2026-02-28

### Added

- **Google ADK agent** -- `LlamaStackAgent` (custom `BaseAgent`) in `agent/` that delegates to Llama Stack Responses API with MCP tools passed inline via `InputToolMCP`. Includes shield moderation, streaming, and tool trace logging.
- **MCP server moved to package** -- `src/rhokp/mcp/server.py` with `rhokp-mcp` console entry point. FastMCP `LoggingMiddleware` for automatic request/response logging.
- **Structured logging** -- `src/rhokp/logging.py` with `JSONFormatter`, request-id propagation via `contextvars`, and `configure_logging()`.
- **Query preprocessing** -- `src/rhokp/preprocessing.py` with synonym expansion (OCP, RHEL, etc.).
- **Pluggable backends** -- `src/rhokp/backends/` with `SearchBackend` protocol, `SolrBackend`, and `MockBackend`.
- **ADK adapter** -- `src/rhokp/adapters/adk.py` for direct Google ADK `FunctionTool` integration.
- **Retrieval evaluation** -- `eval/run_eval.py` with Precision@k and MRR metrics.
- **OpenTelemetry integration** -- optional `observability` extra for distributed tracing.
- **Pre-commit hooks** -- `.pre-commit-config.yaml` with ruff and mypy.
- **CI pipeline** -- `.github/workflows/ci.yml` (lint, test matrix 3.10-3.12, container build + Trivy scan) and `publish.yml` (PyPI via OIDC).

### Changed

- **Client refactored** -- `OKPClient` in `client.py` with connection pooling, circuit breaker, exponential backoff retries, LRU caching, and token budget tracking.
- **Models extracted** -- `models.py` with typed `OKPDocument`, `RetrieveResult`, `FacetCounts`, exception hierarchy (`OKPError`, `OKPConnectionError`, `OKPSearchError`, `OKPResponseError`), and `sanitize_query()`.
- **Config extracted** -- `config.py` with validated, immutable `OKPConfig` from environment variables.
- **`retrieve()` deprecated** -- `src/rhokp/retrieve.py` became a backward-compat shim with `DeprecationWarning`.

## [0.3.0] - 2026-02-27

### Added

- **Codebase review** -- comprehensive review plans in `docs/review-plans/` (expert code review, PM review, architect review, AI architect review, vibe code audit, OKP Solr discovery, maturity scorecard).
- **OKP Solr alignment** -- client aligned with OKP's edismax configuration: field boosting, `<b>` tag highlighting, facet parsing, filter queries, query injection protection, CVE/errata field support, configurable handler path.
- **Architecture documentation** -- `docs/architecture.md` with data flow, design decisions, and module architecture.
- **Air-gap deployment guide** -- `docs/air-gap-deployment.md`.
- **Telemetry documentation** -- `docs/telemetry.md` for User-Agent header segmentation.

## [0.2.0] - 2025-02-28

### Added

- **LangChain retriever** -- Optional `OKPLangChainRetriever` in `rhokp.retrievers` for use in LangChain RAG chains. Install with `pip install rhokp[langchain]`. Supports sync `invoke()` and async `ainvoke()`, env-based defaults for `base_url`/`rows`, and configurable error handling (`raise_on_error`).
- **Optional dependencies** -- `langchain` extra (`langchain-core>=0.3.0,<0.4`) and `dev` extra (pytest, pytest-cov, ruff) in `pyproject.toml`.
- **Tests** -- `tests/test_retrievers.py` for the LangChain retriever (mocked OKP); `tests/conftest.py` skips retriever tests when `langchain-core` is not installed.

### Changed

- Version bump from 0.1.0 to 0.2.0. No breaking changes to `retrieve()` or MCP server.

## [0.1.0] - 2025-02-27

- Initial release: OKP retrieval (`retrieve()`), MCP server (`search_red_hat_docs`).
