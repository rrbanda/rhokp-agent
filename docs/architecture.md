# Architecture: OKP with an AI Agent

## Goal

Use the **Red Hat Offline Knowledge Portal (OKP)** as the retrieval source and an **LLM backend** (e.g. Llama Stack) so an AI agent can answer Red Hat product questions grounded in official documentation.

## High-level flow

```
┌─────────────────┐     ┌──────────────────────────────────────────────────┐
│  User question  │────▶│  LLM backend (e.g. Llama Stack)                  │
│                 │     │  - Responses API: POST /v1/responses              │
│                 │     │  - Agents API: agent + session + turn             │
│                 │     │  - Tools: MCP tool group → OKP search            │
└─────────────────┘     └─────────────────────┬────────────────────────────┘
                                              │
                        ┌─────────────────────▼────────────────────────────┐
                        │  OKP MCP server (optional)                        │
                        │  Tool: search_red_hat_docs(query)                 │
                        └─────────────────────┬────────────────────────────┘
                                              │
                        ┌─────────────────────▼────────────────────────────┐
                        │  Red Hat Offline Knowledge Portal (OKP)          │
                        │  GET /solr/portal/select?q=...&hl=true            │
                        └──────────────────────────────────────────────────┘
```

## Two usage patterns

1. **RAG in one shot (no MCP)**  
   Your script retrieves from OKP, builds a prompt with the context, and calls the Responses API. No tool; good for quick demos and scripting.

2. **Agent with tool**  
   Register an MCP tool group pointing at the OKP MCP server. The agent receives `search_red_hat_docs` and calls it before answering. Best when the agent should decide when to search.

## Components in this repo

| Component      | Purpose |
|----------------|--------|
| `src/rhokp/`   | OKP retrieval: keyword search + highlighting → `context` string for prompts. |
| `mcp_server/`  | MCP server exposing `search_red_hat_docs` for Llama Stack (or other MCP clients). |
| `demo/`        | Script that uses OKP + Responses API; can pass built-in tools (e.g. web_search) for agentic use. |

## Configuration

All endpoints and keys are configured via **environment variables** (see [.env.example](../.env.example) and [running.md](running.md)). No URLs or secrets are hardcoded in the repository.
