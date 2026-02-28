#!/usr/bin/env python3
"""
Demo: answer a question using OKP as RAG context and Llama Stack Responses API.

Uses the Responses API agentic pattern: pass tools in the request so the server
can use them (e.g. web_search, file_search). OKP context is also provided in the
prompt; for full agentic OKP use an MCP toolgroup (see docs).

Flow:
  1. Retrieve relevant docs from OKP.
  2. Build a prompt with that context.
  3. POST to Llama Stack /v1/responses with input + tools.
  4. Print the model answer.

Usage (from repository root):
  export LLAMA_STACK_BASE=https://your-llama-stack-url
  export RHOKP_BASE_URL=http://127.0.0.1:8080
  python demo/ask_okp.py "How do I install OpenShift on bare metal?"

Optional: MODEL=gemini/models/gemini-2.5-pro
  Disable tools: RHOKP_USE_TOOLS=0
"""

import json
import os
import sys
from typing import List, Optional

# Run from repo root: add src to path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))
from rhokp.retrieve import retrieve

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None

LLAMA_BASE = os.environ.get("LLAMA_STACK_BASE", "").rstrip("/")
RHOKP_BASE = os.environ.get("RHOKP_BASE_URL", "http://127.0.0.1:8080")
MODEL = os.environ.get("MODEL", "gemini/models/gemini-2.5-flash")
USE_TOOLS = os.environ.get("RHOKP_USE_TOOLS", "1").strip().lower() in ("1", "true", "yes")


def call_responses_api(
    input_messages: list,
    model: str = MODEL,
    tools: Optional[List[dict]] = None,
) -> dict:
    """POST /v1/responses with input messages, model, and optional tools (agentic)."""
    if not LLAMA_BASE:
        raise SystemExit("Set LLAMA_STACK_BASE to your Llama Stack base URL.")
    url = f"{LLAMA_BASE}/v1/responses"
    body = {
        "input": input_messages,
        "model": model,
        "stream": False,
        "store": False,
    }
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        raise SystemExit(f"Responses API error {e.code}: {err_body}")
    except Exception as e:
        raise SystemExit(f"Request failed: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python demo/ask_okp.py <question>", file=sys.stderr)
        print("  env: LLAMA_STACK_BASE, RHOKP_BASE_URL, MODEL", file=sys.stderr)
        sys.exit(1)
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        sys.exit(1)

    print("Retrieving from OKP...", file=sys.stderr)
    result = retrieve(question, base_url=RHOKP_BASE, rows=5)
    if "error" in result:
        print(f"OKP error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    context = result.get("context", "No documentation found.")
    num_found = result.get("numFound", 0)
    print(f"Found {num_found} doc(s). Calling Llama Stack...", file=sys.stderr)

    system_content = (
        "You are a Red Hat expert. Answer the user's question using ONLY the following "
        "documentation excerpts. If the excerpts do not contain enough information, say so. "
        "Do not invent details."
    )
    user_content = f"Documentation excerpts:\n\n{context}\n\nQuestion: {question}"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
    input_for_api = [{"role": m["role"], "content": m["content"]} for m in messages]

    # Agentic: pass tools so the server/model can use them (e.g. web_search, file_search)
    tools = [{"type": "web_search"}] if USE_TOOLS else None
    response = call_responses_api(input_for_api, model=MODEL, tools=tools)

    # Extract assistant text (structure may vary by Llama Stack version)
    out = response.get("output") or response.get("output_text") or response
    if isinstance(out, list):
        for item in out:
            if isinstance(item, dict):
                if item.get("type") == "message" and item.get("role") == "assistant":
                    c = item.get("content")
                    if isinstance(c, str):
                        print(c)
                        return
                    if isinstance(c, list):
                        for part in c:
                            if isinstance(part, dict) and part.get("type") == "output_text":
                                print(part.get("text", ""))
                                return
    if isinstance(out, dict) and "content" in out:
        c = out["content"]
        if isinstance(c, str):
            print(c)
            return
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    print(part.get("text", ""))
                    return
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
