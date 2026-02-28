# Containers (Podman + UBI)

MCP server and demo client run as separate UBI-based containers.

**Pre-built images (Quay):**
- `quay.io/rbrhssa/rhokp-mcp:latest`
- `quay.io/rbrhssa/rhokp-demo:latest`

Use these in place of `rhokp-mcp` / `rhokp-demo` if you don't build locally (e.g. `podman run ... quay.io/rbrhssa/rhokp-mcp:latest`).

- **Full plan (design, networking, secrets):** [../docs/podman-ubi-plan.md](../docs/podman-ubi-plan.md)
- **Step-by-step (verified run order):** [../docs/containers-step-by-step.md](../docs/containers-step-by-step.md)

## Quick reference

**Network:**
```bash
podman network create rhokp-net
```

**Build (from repo root):**
```bash
podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .
podman build -f containers/demo/Dockerfile -t rhokp-demo .
```

**Run MCP server** (after OKP is running on `rhokp-net` as `okp`):
```bash
podman run -d --name rhokp-mcp -p 8010:8010 \
  -e RHOKP_BASE_URL=http://okp:8080 \
  --network rhokp-net rhokp-mcp
```

**Run demo (one-off):**
```bash
podman run --rm \
  -e RHOKP_BASE_URL=http://okp:8080 \
  -e LLAMA_STACK_BASE=https://your-llama-stack-url \
  --network rhokp-net \
  rhokp-demo "How do I install OpenShift on bare metal?"
```

No secrets in images; pass credentials at runtime.
