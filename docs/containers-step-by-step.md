# Step-by-step: Run MCP and demo as Podman containers (verified)

This is the **executed** sequence. Both images build and run; MCP server responds to `/health` and `tools/list`; demo container runs the script (fails as expected when OKP/LLama Stack are not configured).

---

## Prerequisites

- Podman installed.
- Optional: `podman login registry.redhat.io` if your environment requires it for UBI images.
- Repository at e.g. `~/code/rhokp-agent`; all commands from **repo root**.

---

## Step 1: Create network

```bash
podman network create rhokp-net
```

*(If it already exists, you'll see "already exists"; that's fine.)*

---

## Step 2: Build MCP server image

```bash
cd /path/to/rhokp-agent
podman build -f containers/mcp-server/Dockerfile -t rhokp-mcp .
```

**Verified:** Build succeeds; image `localhost/rhokp-mcp:latest` created (UBI 9 + Python 3.9, FastAPI, uvicorn).

---

## Step 3: Run MCP server container

Start OKP first if you want the MCP server to actually reach it (see step 5). For a quick check, you can run MCP with `RHOKP_BASE_URL=http://okp:8080`; the server will start and only fail when a client calls `tools/call` and it tries to contact OKP.

```bash
podman run -d --name rhokp-mcp -p 8010:8010 \
  -e RHOKP_BASE_URL=http://okp:8080 \
  --network rhokp-net rhokp-mcp
```

---

## Step 4: Verify MCP server

```bash
curl -s http://localhost:8010/health
# Expect: {"status":"ok","service":"okp-mcp"}

curl -s -X POST http://localhost:8010/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# Expect: JSON with "result":{"tools":[{"name":"search_red_hat_docs",...}]}
```

**Verified:** Both return the expected responses.

---

## Step 5: (Optional) Start OKP on the same network

If you run OKP as a container, attach it to `rhokp-net` and use the container name so MCP and demo can reach it:

```bash
podman run -d --name okp -p 8080:8080 -p 8443:8443 --memory=4g \
  -e ACCESS_KEY=<your_access_key> -e SOLR_MEM=1g \
  --network rhokp-net \
  registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
```

Wait a few minutes for Solr. Then MCP and demo can use `RHOKP_BASE_URL=http://okp:8080`.

---

## Step 6: Build demo image

```bash
podman build -f containers/demo/Dockerfile -t rhokp-demo .
```

**Verified:** Build succeeds; image `localhost/rhokp-demo:latest` created.

---

## Step 7: Run demo (one-off)

With OKP and Llama Stack available:

```bash
podman run --rm \
  -e RHOKP_BASE_URL=http://okp:8080 \
  -e LLAMA_STACK_BASE=https://your-llama-stack-url \
  --network rhokp-net \
  rhokp-demo "How do I install OpenShift on bare metal?"
```

If OKP is not on the network (no container named `okp`), you'll see e.g. `OKP error: ... Name or service not known`. If OKP is reachable but `LLAMA_STACK_BASE` is unset, the script exits with "Set LLAMA_STACK_BASE". Both are expected when that component is missing.

**Verified:** Demo container runs, executes `ask_okp.py`, and fails as above when OKP or Llama Stack is not configured.

---

## Step 8: Cleanup (optional)

```bash
podman stop rhokp-mcp
podman rm rhokp-mcp
# If you started OKP: podman stop okp && podman rm okp
```

---

## Summary

| Step | Action | Status |
|------|--------|--------|
| 1 | Create network `rhokp-net` | Verified |
| 2 | Build `rhokp-mcp` image | Verified |
| 3 | Run MCP container | Verified |
| 4 | Curl /health and /mcp tools/list | Verified |
| 5 | Start OKP on rhokp-net (optional) | Documented |
| 6 | Build `rhokp-demo` image | Verified |
| 7 | Run demo one-off | Verified (fails correctly without OKP/LLAMA_STACK_BASE) |

The plan in [podman-ubi-plan.md](podman-ubi-plan.md) describes design and options; this file is the minimal, runnable sequence that was executed and checked.
