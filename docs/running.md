# Running RHOKP

## Quick start (Podman / Docker Compose)

The fastest path to a working OKP + MCP server:

```bash
# Core services only (OKP + MCP server)
podman-compose up rhokp mcp-server

# Full stack (adds ADK web UI -- needs LLAMA_STACK_BASE_URL)
cp agent/.env.example agent/.env   # fill in your values
podman-compose --profile full up
```

This starts:

| Service | Port | Description |
|---------|------|-------------|
| `rhokp` | 8080 | Red Hat Offline Knowledge Portal (Solr) |
| `mcp-server` | 8010 | MCP server exposing `search_red_hat_docs` |
| `adk-web` | 8000 | Google ADK web UI (optional, `full` profile) |

Solr needs 1--2 minutes to initialize. The MCP server waits for the OKP
health check to pass before starting.

## Running OKP standalone

OKP runs as a container. You need:

- Red Hat registry access and an **OKP access key** (for encrypted content). Do not commit the key; pass it at runtime.
- Sufficient memory for Solr (recommended: 4 GB container memory, 1 GB for Solr).

```bash
podman run --rm -p 8080:8080 --memory=4g \
  -e ACCESS_KEY=<your_access_key> \
  -e SOLR_MEM=1g \
  -d registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
```

Wait 1--2 minutes for Solr to come up, then verify:

```bash
curl "http://localhost:8080/solr/portal/select?q=test&rows=1&wt=json"
```

## MCP server

Run locally (no container):

```bash
pip install -e .[mcp]
export RHOKP_BASE_URL=http://127.0.0.1:8080
rhokp-mcp
```

Or use the pre-built container:

```bash
podman run -d --name rhokp-mcp -p 8010:8010 \
  -e RHOKP_BASE_URL=http://<okp-host>:8080 \
  quay.io/rbrhssa/rhokp-mcp:latest
```

The MCP endpoint is `http://localhost:8010/mcp` (JSON-RPC over HTTP).

## Retrieval CLI

```bash
pip install -e .
python -m rhokp "install OpenShift"
python -m rhokp --verbose "RHEL 9 kernel tuning"    # debug logging
python -m rhokp --context-only "ansible automation"  # LLM context only
```

## Environment variables

Copy [.env.example](../.env.example) to `.env` (do not commit `.env`) and set:

| Variable | Description |
|----------|-------------|
| `RHOKP_BASE_URL` | OKP base URL (default `http://127.0.0.1:8080`). |
| `RHOKP_RAG_ROWS` | Max doc snippets to retrieve (default 5). |
| `MCP_HOST` | MCP server bind address (default `0.0.0.0`). |
| `MCP_PORT` | MCP server port (default `8010`). |
| `LLAMA_STACK_BASE_URL` | Llama Stack base URL (for ADK agent). |
| `MODEL` | Model identifier (default `gemini/models/gemini-2.5-pro`). |
