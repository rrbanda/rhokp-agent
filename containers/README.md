# Containers

MCP server and ADK agent run as separate containers.

**Pre-built images (Quay):**

| Image | Description |
|-------|-------------|
| `quay.io/rbrhssa/rhokp-mcp:latest` | MCP server (OKP search tools) |
| `quay.io/rbrhssa/rhokp-adk:latest` | ADK agent + web UI |
| Tags: `latest`, `v0.5.0` | |

## Compose (recommended)

From the repo root:

```bash
# OKP + MCP server
podman-compose up rhokp mcp-server

# Full stack (OKP + MCP + ADK web UI)
podman-compose --profile full up
```

See [podman-compose.yaml](../podman-compose.yaml).

## Manual

**Build (from repo root):**

```bash
podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .
podman build -f containers/adk-agent/Dockerfile -t rhokp-adk .
```

**Run MCP server** (after OKP is running):

```bash
podman network create rhokpnet
podman run -d --name rhokp-mcp -p 8010:8010 \
  -e RHOKP_BASE_URL=http://okp:8080 \
  --network rhokpnet quay.io/rbrhssa/rhokp-mcp:latest
```

No secrets in images; pass credentials at runtime.
