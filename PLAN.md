# Production-grade plan: rhokp-agent repository

This document outlines how the [rhokp-agent](https://github.com/rrbanda/rhokp-agent) repo is structured for open source: no secrets, env-only configuration, and professional layout.

---

## Goals

1. **Single-purpose repo**: Demo and tools for using the Red Hat Offline Knowledge Portal (OKP) with an AI agent (e.g. Llama Stack).
2. **No secrets**: No API keys, tokens, or internal URLs in code or committed files. All configuration via environment variables; document with `.env.example`.
3. **Production-grade OSS**: Clear README, docs, `.gitignore`, optional CONTRIBUTING/SECURITY, permissive license (Apache-2.0 already present).

---

## Repository layout

```
rhokp-agent/
├── .gitignore
├── .env.example
├── README.md
├── PLAN.md                 # This file (can remove or keep for maintainers)
├── LICENSE
├── pyproject.toml          # Optional: project metadata, deps
├── requirements.txt        # For demo + MCP server (or use pyproject.toml only)
├── src/
│   └── rhokp/
│       ├── __init__.py
│       └── retrieve.py     # OKP search → context (from rhokp_retrieve.py)
├── mcp_server/             # MCP server (optional component)
│   ├── README.md
│   ├── requirements.txt
│   └── server.py           # FastAPI, tools/list + tools/call
├── demo/                   # Demo script(s)
│   ├── README.md
│   ├── ask_okp.py          # OKP retrieve + Llama Stack Responses API
│   └── .env.example        # Optional: demo-specific env template
└── docs/
    ├── architecture.md     # Diagram + flows (generic, no internal URLs)
    └── running.md          # How to run OKP, demo, MCP (env vars only)
```

---

## No-secrets checklist

- [ ] **No hardcoded URLs** in code: use `os.environ.get("RHOKP_BASE_URL", "http://127.0.0.1:8080")` and similar; default to localhost or empty.
- [ ] **No ACCESS_KEY / tokens** in repo: OKP access key is user-supplied (e.g. Podman `-e ACCESS_KEY=...`); document in README only.
- [ ] **`.env` in .gitignore**: so users can copy `.env.example` to `.env` locally without risk of commit.
- [ ] **README and docs**: use placeholders like `$LLAMA_STACK_BASE`, `$RHOKP_BASE_URL`, `<your_access_key>`; no real keys or internal hostnames.
- [ ] **Pre-push**: quick scan for `password`, `secret`, `api_key`, `token` in tracked files (or CI step).

---

## Content to bring from reference implementation

| Source (rhoaibu-cluster-1)        | Destination in rhokp-agent        | Adjustments |
|----------------------------------|-----------------------------------|-------------|
| tools/rhokp-rag/rhokp_retrieve.py| src/rhokp/retrieve.py             | Keep env-only; add `__init__.py` |
| tools/rhokp-rag/mcp_server/*     | mcp_server/                       | Import from `src.rhokp.retrieve`; env-only |
| demos/.../okp-agent-demo/ask_okp.py | demo/ask_okp.py                | Import from `src.rhokp`; remove internal URL from docstring |
| demos/.../okp-agent-demo/README.md | demo/README.md                  | Generic instructions; env vars only |
| docs/PLAN-OKP-AI-AGENT-DEMO.md   | docs/architecture.md + running.md| Strip internal URLs; generic “your Llama Stack”, “your OKP” |

---

## Optional open source boilerplate

- **CONTRIBUTING.md**: How to open issues, PRs, and code style (e.g. Python 3.9+, no secrets).
- **SECURITY.md**: How to report vulnerabilities (e.g. GitHub Security Advisories); no sensitive data in issues.
- **CODE_OF_CONDUCT.md**: Link to Contributor Covenant or similar (optional).

---

## Implementation order

1. Add `.gitignore` and `.env.example`.
2. Add `src/rhokp/` (retrieve module).
3. Add `mcp_server/` (with local import path to `src.rhokp` or install as package).
4. Add `demo/ask_okp.py` and `demo/README.md`.
5. Add `docs/architecture.md` and `docs/running.md` (generic).
6. Rewrite root `README.md`: project description, quick start, links to docs/demo/MCP.
7. Add `requirements.txt` (and optionally `pyproject.toml`).
8. Optional: CONTRIBUTING, SECURITY, CODE_OF_CONDUCT.
9. Final pass: grep for secrets/URLs, run demo in a clean env to verify.

---

## Post-push

- Ensure no `.env` or secrets in history (`git log -p` spot-check or use tools like `git-secrets`).
- Tag first release (e.g. `v0.1.0`) after first production-grade push.
