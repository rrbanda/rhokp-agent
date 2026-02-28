# Security

## Reporting a vulnerability

If you believe you have found a security vulnerability, please do **not** open a public issue. Report it privately, for example via [GitHub Security Advisories](https://github.com/rrbanda/rhokp-agent/security/advisories/new) or by contacting the maintainers through appropriate channels.

## Configuration and secrets

- This repository does not contain API keys, tokens, or other secrets.
- Configure OKP and LLM endpoints via environment variables (see [.env.example](.env.example)).
- Do not commit `.env` or any file containing real credentials; `.env` is listed in [.gitignore](.gitignore).
