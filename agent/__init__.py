"""RHOKP ADK agent package.

Exports ``root_agent`` for discovery by ``adk web`` and ``adk api_server``.
All configuration is read from environment variables -- see .env.example.
"""

from __future__ import annotations

import os

from agent.agent import LlamaStackAgent

# Wire up OpenTelemetry providers when OTEL_EXPORTER_OTLP_ENDPOINT (or the
# per-signal variants) are set.  ADK's built-in tracing (trace_agent_invocation,
# trace_tool_call, trace_call_llm) and our client.py OTel spans will then
# export via OTLP.  When the env var is absent this is a no-op.
try:
    from google.adk.telemetry.setup import maybe_set_otel_providers

    maybe_set_otel_providers()
except Exception:
    pass

root_agent = LlamaStackAgent(
    name="rhokp_agent",
    description=(
        "Red Hat Offline Knowledge Portal assistant. "
        "Answers questions about Red Hat products using official "
        "documentation, solutions, CVEs, and errata from RHOKP."
    ),
    llama_stack_url=os.environ.get("LLAMA_STACK_BASE_URL", ""),
    model_id=os.environ.get("MODEL", "gemini/models/gemini-2.5-pro"),
    mcp_server_url=os.environ.get("MCP_SERVER_URL", "http://localhost:8010/mcp"),
)
