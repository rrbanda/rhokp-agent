# OSS Roadmap: From Demo to Production-Ready Open Source

This document is an **expert review** of the rhokp-agent codebase and a **concrete plan** to evolve it from a demo into a real, maintainable open source project.

---

## Part 1: Expert code review

### Strengths (already in place)

| Area | Status |
|------|--------|
| **No secrets** | Env-only config; `.env` gitignored; `.env.example` with placeholders; documented in CONTRIBUTING and SECURITY. |
| **Clear scope** | Single purpose: OKP retrieval + MCP + demo for LLM agents. |
| **Layout** | `src/` package, separate `mcp_server/` and `demo/`, `docs/` — standard and navigable. |
| **Installability** | `pyproject.toml` with optional deps; `pip install -e .` and `python -m rhokp` work. |
| **Containers** | Dockerfiles (UBI 9, non-root); no secrets in image; runtime env only. |
| **Docs** | README, architecture, running, containers, plan; all use generic placeholders. |
| **Legal/community** | LICENSE (Apache-2.0), CONTRIBUTING, SECURITY. |

### Gaps and risks

| Gap | Risk | Priority |
|-----|------|----------|
| **No tests** | Regressions, fear of refactoring, contributors can’t validate. | P0 |
| **No CI** | Broken main, no automated lint/test on PR. | P0 |
| **Unversioned API** | `retrieve()` return shape or MCP contract could change without notice. | P1 |
| **Single maintainer** | Bus factor; no CODE_OF_CONDUCT or explicit maintainer contact. | P1 |
| **No changelog** | Users can’t see what changed between versions. | P1 |
| **Demo script not installable** | `demo/ask_okp.py` relies on `sys.path` hack; not a proper entry point. | P2 |
| **MCP path coupling** | MCP server mutates `sys.path`; fragile when run from containers or different CWD. | P2 |
| **No type hints on public API** | Harder for IDEs and static analysis; no mypy. | P2 |
| **Containers not in CI** | Image build/tag not verified on every change. | P2 |
| **No supported versions doc** | OKP/Llama Stack compatibility not stated. | P3 |

### Code-level notes

- **`src/rhokp/retrieve.py`**: Clean, stdlib-only, good error handling. Return type is a loose `dict`; consider a `TypedDict` or dataclass for the return value so the contract is explicit and stable.
- **`mcp_server/server.py`**: Relies on `sys.path.insert` to find `rhokp`. Works when run from repo root or with `PYTHONPATH=/app/src` in container. Prefer installing the package in the container so the server just `from rhokp.retrieve import retrieve` with no path hacks.
- **`demo/ask_okp.py`**: Same path hack; no dependency on `rhokp` as an installed package. Response parsing is defensive (multiple shapes); consider documenting the minimal Responses API shape the demo expects.
- **Containers**: Use `COPY src/` and `ENV PYTHONPATH=/app/src`; consider `pip install -e .` in the image so the package is first-class and path hacks can be removed.

---

## Part 2: Plan to become “real” OSS

### Phase 1: Quality and automation (weeks 1–2)

**Goal:** Main branch is always testable and lint-clean; every PR is checked.

1. **Add tests**
   - **Unit tests for `retrieve()`**: Use `unittest.mock` or `responses`/`httpx` to mock `urllib.request`; test success (parse response, check `context`, `numFound`, `docs`), HTTP errors (4xx/5xx), timeouts, and malformed JSON. No real OKP needed.
   - **MCP server tests**: Use `httpx.AsyncClient` or `TestClient(FastAPI)`; test `GET /health`, `POST /mcp` with `initialize`, `tools/list`, and `tools/call` (valid query + error cases). Mock `retrieve()` so no OKP required.
   - **Location**: `tests/` at repo root. Structure: `tests/test_retrieve.py`, `tests/test_mcp_server.py`. Run with `pytest` or `python -m pytest`.

2. **Add CI (GitHub Actions)**
   - **Lint**: Run `ruff check` and `ruff format --check` (or flake8 + black) on Python files.
   - **Tests**: `pip install -e ".[mcp]"` then `pytest tests/ -v`. Python matrix: 3.9, 3.10, 3.11 (or 3.9 + latest).
   - **Optional**: Build container images (no push) to ensure Dockerfiles don’t break.
   - **Branch**: Run on `push` to `main` and on `pull_request` to `main`.

3. **Dependencies for dev**
   - Add to `pyproject.toml`: `[project.optional-dependencies] dev = ["pytest", "pytest-asyncio", "httpx", "ruff"]` (or equivalent). Document in CONTRIBUTING: “Install with `pip install -e '.[mcp,dev]'` to run tests.”

**Deliverables:** `tests/`, CI workflow file (e.g. `.github/workflows/ci.yml`), updated CONTRIBUTING with “run tests locally” and “CI runs on PR”.

---

### Phase 2: API contract and versioning (weeks 2–3)

**Goal:** Clear, stable contract for the library and MCP; semantic versioning.

1. **Stabilize and document the public API**
   - **Library**: Document in README or `docs/api.md`: “Public API is `rhokp.retrieve.retrieve(query, base_url=..., rows=...)`. Return value is a dict with keys: `query`, `numFound`, `docs`, `context`; on error, `error` (and optionally `details`). We will not remove or rename these keys in 0.x without a deprecation period.”
   - **MCP**: Document in `mcp_server/README.md`: “This server implements JSON-RPC 2.0 over HTTP. Methods: `initialize`, `tools/list`, `tools/call`. Tool name: `search_red_hat_docs` with argument `query`. Response shape: …” Add a short “Protocol” or “Contract” section.

2. **Semantic versioning**
   - Adopt SemVer in README: “We use semantic versioning (e.g. 0.2.0).”
   - In `pyproject.toml`, keep `version = "0.1.0"` (or bump to 0.2.0 when you cut the first post-OSS-plan release).

3. **Changelog**
   - Add `CHANGELOG.md` at repo root. Format: “## [Unreleased]”, “## [0.1.0] - YYYY-MM-DD” with bullet list of changes. From now on, every release gets an entry.
   - In CONTRIBUTING: “Significant changes should be noted in CHANGELOG.md under [Unreleased].”

4. **Releases and tags**
   - Tag releases: `v0.1.0`, `v0.2.0`. In GitHub, create a Release with the same tag and copy the CHANGELOG section for that version into the release notes.
   - Optional: Document “Supported versions” (e.g. “Tested with OKP image X, Llama Stack compatible with Responses API as of 2024”) in README or `docs/compatibility.md`.

**Deliverables:** `docs/api.md` (or equivalent), updated MCP README contract, `CHANGELOG.md`, SemVer stated in README, first release tag and GitHub Release.

---

### Phase 3: Project hygiene and community (weeks 3–4)

**Goal:** Clear maintainer expectations, code of conduct, and container publishing.

1. **CODE_OF_CONDUCT.md**
   - Add Contributor Covenant (https://www.contributor-covenant.org/). Link from README: “This project adheres to a Code of Conduct (see CODE_OF_CONDUCT.md).”

2. **Maintainer and support**
   - In README: “Maintainer: …” or “Maintained by …”. Optionally: “We do not guarantee response time for issues; for commercial support contact ….”
   - In CONTRIBUTING: “We welcome PRs; please open an issue first for large changes.”

3. **Container images**
   - You already push to Quay. Document in README: “Container images: `quay.io/rbrhssa/rhokp-mcp:latest`, `quay.io/rbrhssa/rhokp-demo:latest`. Use the same tag as the release (e.g. `v0.1.0`) for reproducibility.”
   - Optional: CI job to build and push images on tag (e.g. on `v*`) using Quay credentials in GitHub secrets.

4. **Remove path hacks (optional but recommended)**
   - In both `mcp_server/server.py` and `demo/ask_okp.py`, remove `sys.path.insert`. In Dockerfiles, add `RUN pip install -e .` (and for MCP, `pip install -e ".[mcp]"`) so the package is installed. Then the server and demo just `from rhokp.retrieve import retrieve`. This makes running from any CWD and from containers consistent.

**Deliverables:** CODE_OF_CONDUCT.md, README/CONTRIBUTING updates, container image docs (and optionally CI push on tag).

---

### Phase 4: Polish and scale (ongoing)

- **Type hints**: Add to `retrieve()` and MCP request/response paths; run `mypy` in CI (strict optional).
- **Pre-commit**: Add `.pre-commit-config.yaml` (ruff, black, mypy) and document in CONTRIBUTING.
- **Benchmarks / smoke**: Optional job that runs the demo against a real OKP + Llama Stack (e.g. in a private runner or scheduled run) to catch integration breakage.
- **Advisory board**: If the project grows, document governance (e.g. “We follow community feedback; breaking changes are discussed in issues.”).

---

## Summary checklist

| Item | Phase | Done |
|------|--------|------|
| Unit tests for `retrieve()` | 1 | |
| Tests for MCP server | 1 | |
| CI: lint + test on PR | 1 | |
| Document public API + MCP contract | 2 | |
| CHANGELOG.md + SemVer | 2 | |
| First release tag (e.g. v0.2.0) | 2 | |
| CODE_OF_CONDUCT.md | 3 | |
| Maintainer/support in README | 3 | |
| Container image docs (Quay) | 3 | |
| Remove path hacks, install package in containers | 3 | |

---

## Image push confirmation

Container images have been pushed to:

- **quay.io/rbrhssa/rhokp-mcp:latest**
- **quay.io/rbrhssa/rhokp-demo:latest**

Use these in README and in the “Supported versions” / deployment docs. For releases, consider tagging images with the same version as the repo (e.g. `quay.io/rbrhssa/rhokp-mcp:v0.2.0`).
