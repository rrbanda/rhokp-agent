# Demo: OKP + Llama Stack Responses API

Answer Red Hat questions using the **Red Hat Offline Knowledge Portal (OKP)** as retrieval and **Llama Stack** (Responses API) for the LLM.

## Quick run

1. **Start OKP** (if not already running). See [docs/running.md](../docs/running.md). Example with Podman:

   ```bash
   podman run --rm -p 8080:8080 -p 8443:8443 --memory=4g \
     -e ACCESS_KEY=<your_access_key> -e SOLR_MEM=1g \
     -d registry.redhat.io/offline-knowledge-portal/rhokp-rhel9:latest
   ```
   Wait a few minutes for Solr to start.

2. **Set environment** (use your own Llama Stack URL; do not commit real values):

   ```bash
   export LLAMA_STACK_BASE=https://your-llama-stack.example.com
   export RHOKP_BASE_URL=http://127.0.0.1:8080
   # Optional: MODEL=gemini/models/gemini-2.5-pro
   # Optional: RHOKP_USE_TOOLS=0 to disable passing tools (web_search) to the API
   ```

3. **Run the script** from the repository root:

   ```bash
   python demo/ask_okp.py "How do I install OpenShift on bare metal?"
   ```

The script retrieves snippets from OKP, sends them with your question to Llama Stack, and prints the model's answer. By default it also passes `tools=[{"type": "web_search"}]` to the Responses API (agentic pattern). Set `RHOKP_USE_TOOLS=0` to disable.

## Agent + MCP tool

For an agent that calls OKP via a tool (e.g. Llama Stack Agents API), see [docs/architecture.md](../docs/architecture.md) and [mcp_server/README.md](../mcp_server/README.md).
