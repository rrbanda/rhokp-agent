# OKP MCP Server

Exposes Red Hat Offline Knowledge Portal (OKP) search as a single [MCP](https://modelcontextprotocol.io/) tool `search_red_hat_docs` for use with Llama Stack and other MCP clients.

## Prerequisites

- OKP running and reachable (set `RHOKP_BASE_URL` if not `http://127.0.0.1:8080`)
- Python 3.9+

## Install and run

From the **repository root**:

```bash
pip install -r mcp_server/requirements.txt
export RHOKP_BASE_URL=http://127.0.0.1:8080   # optional
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8010
```

## Register with Llama Stack

Ensure Llama Stack can reach this server (e.g. deploy on cluster or use a tunnel). Then register a tool group:

```bash
curl -X POST "$LLAMA_STACK_BASE/v1/toolgroups" -H "Content-Type: application/json" \
  -d '{
    "toolgroup_id": "okp-search",
    "provider_id": "model-context-protocol",
    "mcp_endpoint": { "uri": "http://<this-server-url>/mcp" }
  }'
```

Create an agent with `toolgroups: ["okp-search"]` so it can call `search_red_hat_docs` before answering.

## Endpoints

- **POST /mcp** — JSON-RPC 2.0: `initialize`, `tools/list`, `tools/call`
- **GET /health** — Health check
