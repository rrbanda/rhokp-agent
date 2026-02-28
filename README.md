# rhokp-agent

Use the **Red Hat Offline Knowledge Portal (OKP)** with an AI agent: retrieve Red Hat documentation and feed it to an LLM (e.g. [Llama Stack](https://github.com/red-hat-data-services/llama-stack)) for grounded answers.

## Features

- **OKP retrieval** — Keyword search with highlighting over the OKP Solr API, producing a `context` string for RAG prompts.
- **MCP server** — Expose a single tool `search_red_hat_docs` so agents can search OKP on demand (Model Context Protocol).
- **Demo script** — Example: OKP retrieve → Llama Stack Responses API → print answer.

No API keys or internal URLs are stored in the repo; configuration is via environment variables (see [.env.example](.env.example)).

## Quick start

1. **Clone and set environment**

   ```bash
   git clone https://github.com/rrbanda/rhokp-agent.git
   cd rhokp-agent
   cp .env.example .env   # edit .env with your values; do not commit
   ```

2. **Start OKP** (see [docs/running.md](docs/running.md)). Example with Podman:

   ```bash
   podman run --rm -p 8080:8080 -p 8443:8443 --memory=4g \
     -e ACCESS_KEY=<your_access_key> -e SOLR_MEM=1g \
     -d registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
   ```
   Wait a few minutes for Solr.

3. **Run the demo** (requires a Llama Stack instance and `LLAMA_STACK_BASE` set):

   ```bash
   export LLAMA_STACK_BASE=https://your-llama-stack-url
   export RHOKP_BASE_URL=http://127.0.0.1:8080
   python demo/ask_okp.py "How do I install OpenShift on bare metal?"
   ```

## Repository layout

| Path | Description |
|------|-------------|
| [src/rhokp/](src/rhokp/) | OKP retrieval library (`retrieve()`). |
| [mcp_server/](mcp_server/) | MCP server for the `search_red_hat_docs` tool. |
| [demo/](demo/) | Demo: OKP + Llama Stack Responses API. |
| [docs/](docs/) | [Architecture](docs/architecture.md) and [running](docs/running.md) notes. |
| [.env.example](.env.example) | Example environment variables (copy to `.env`; do not commit). |

## Requirements

- Python 3.9+
- OKP instance (e.g. Podman or in-cluster)
- For the demo: a Llama Stack (or compatible) endpoint

## Verify installation

With OKP running at `http://127.0.0.1:8080`:

```bash
# Optional: install the package so `python -m rhokp` works
pip install -e .

# Test retrieval (prints JSON with docs and context)
python -m rhokp "install OpenShift"
# Or without installing: PYTHONPATH=src python -m rhokp "install OpenShift"

# Test MCP server
pip install -r mcp_server/requirements.txt
uvicorn mcp_server.server:app --host 127.0.0.1 --port 8010 &
curl -s http://127.0.0.1:8010/health
curl -s -X POST http://127.0.0.1:8010/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Demo script: set `LLAMA_STACK_BASE` and run `python demo/ask_okp.py "your question"`; it will retrieve from OKP then call Llama Stack.

## License

Apache-2.0. See [LICENSE](LICENSE).
