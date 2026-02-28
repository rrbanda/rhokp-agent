# Contributing to rhokp-agent

Thank you for your interest in contributing.

## Code and pull requests

- Use Python 3.9+ compatible code.
- Do **not** add secrets, API keys, or internal URLs to the repository. Configuration is via environment variables only; document new variables in `.env.example`.
- Keep the scope focused: OKP retrieval, MCP server for OKP search, and demos that use OKP with an LLM backend.

## Submitting changes

1. Open an issue or pick an existing one to discuss the change.
2. Fork the repo, create a branch, and make your changes.
3. Ensure any new or modified code paths use env-based configuration (no hardcoded credentials or internal hostnames).
4. Open a pull request with a short description and reference to the issue if applicable.

## Reporting security issues

Do **not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md).
