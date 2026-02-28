# Running OKP and the demo

## Red Hat Offline Knowledge Portal (OKP)

OKP runs as a container. You need:

- Red Hat registry access and an **OKP access key** (for encrypted content). Do not commit the key; set it when starting the container.
- Sufficient memory for Solr (recommended: 4 GB container memory, 1 GB for Solr).

### Example: Podman

```bash
podman run --rm -p 8080:8080 -p 8443:8443 --memory=4g \
  -e ACCESS_KEY=<your_access_key> \
  -e SOLR_MEM=1g \
  -d registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
```

Wait a few minutes for Solr to come up. Then:

- HTTP: `http://127.0.0.1:8080`
- HTTPS: `https://127.0.0.1:8443`

Search API: `GET http://127.0.0.1:8080/solr/portal/select?q=<query>&rows=5&wt=json&hl=true&hl.fl=main_content,title&hl.snippets=2&hl.fragsize=300`

## Environment variables

Copy [.env.example](../.env.example) to `.env` (do not commit `.env`) and set:

| Variable           | Description |
|--------------------|-------------|
| `RHOKP_BASE_URL`   | OKP base URL (default `http://127.0.0.1:8080`). |
| `RHOKP_RAG_ROWS`   | Max doc snippets to retrieve (optional; default 5). |
| `LLAMA_STACK_BASE` | Your Llama Stack base URL (for the demo). |
| `MODEL`            | Model identifier from `GET /v1/models` (optional; demo has a default). |
| `RHOKP_USE_TOOLS`  | Demo: pass `tools` (e.g. web_search) to Responses API; set to `0` to disable (default 1). |

## Retrieval CLI

From the repository root, either install the package or set `PYTHONPATH`:

```bash
pip install -e .   # then:
python -m rhokp "install OpenShift"

# Or without installing:
PYTHONPATH=src python -m rhokp "install OpenShift"
```

Prints JSON with `query`, `numFound`, `docs`, and `context`.

## Demo (Responses API)

From the repository root:

```bash
export LLAMA_STACK_BASE=https://your-llama-stack-url
export RHOKP_BASE_URL=http://127.0.0.1:8080
python demo/ask_okp.py "How do I install OpenShift on bare metal?"
```

See [demo/README.md](../demo/README.md) for more detail.

## MCP server (optional)

From the repository root:

```bash
pip install -r mcp_server/requirements.txt
export RHOKP_BASE_URL=http://127.0.0.1:8080
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8010
```

Then register the server URL with your Llama Stack as an MCP tool group and create an agent that uses the `okp-search` tool group. See [mcp_server/README.md](../mcp_server/README.md).
