#!/usr/bin/env python3
"""
MCP server exposing OKP search as a single tool for Llama Stack (and other MCP clients).

Implements JSON-RPC 2.0 over HTTP: initialize, tools/list, tools/call.
Run from repository root: uvicorn mcp_server.server:app --host 0.0.0.0 --port 8010

Environment:
  RHOKP_BASE_URL  OKP base URL (default http://127.0.0.1:8080)
  RHOKP_RAG_ROWS  Max docs to return (default 5)
"""

import os
import sys

# Ensure repo root/src is on path when run from anywhere
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))
from rhokp.retrieve import retrieve

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="OKP MCP Server", version="0.1.0")

OKP_BASE = os.environ.get("RHOKP_BASE_URL", "http://127.0.0.1:8080")
OKP_ROWS = int(os.environ.get("RHOKP_RAG_ROWS", "5"))

TOOL_DEF = {
    "name": "search_red_hat_docs",
    "title": "Search Red Hat documentation",
    "description": "Search the Red Hat Offline Knowledge Portal for product documentation, solutions, and how-to guides. Use this when the user asks about Red Hat products, OpenShift, RHEL, or other Red Hat technologies.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'how to install OpenShift', 'RHEL kernel tuning')",
            }
        },
        "required": ["query"],
    },
}


@app.post("/mcp")
async def mcp_jsonrpc(request: Request):
    """Handle MCP JSON-RPC 2.0 requests (initialize, tools/list, tools/call)."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            },
        )

    msg_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "okp-mcp", "version": "0.1.0"},
                },
            }
        )

    if method == "tools/list":
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": [TOOL_DEF], "nextCursor": None},
            }
        )

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "search_red_hat_docs":
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"},
                }
            )
        query = (arguments.get("query") or "").strip()
        if not query:
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": "Error: 'query' is required."}],
                        "isError": True,
                    },
                }
            )
        result = retrieve(query, base_url=OKP_BASE, rows=OKP_ROWS)
        if "error" in result:
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": f"OKP error: {result.get('error', 'Unknown')}"}],
                        "isError": True,
                    },
                }
            )
        text = result.get("context", "No results found.")
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            }
        )

    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "okp-mcp"}
