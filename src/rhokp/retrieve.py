"""
Red Hat Offline Knowledge Portal (OKP) retrieval for RAG and AI agents.

Uses the OKP search API (Solr portal/select with highlighting) to retrieve
relevant documentation snippets. The container image typically does not include
semantic search; this module uses keyword search with highlighting to produce
a context string suitable for LLM prompts.

Usage:
  from rhokp import retrieve
  result = retrieve("how to install OpenShift", base_url="http://127.0.0.1:8080")
  context = result["context"]
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = os.environ.get("RHOKP_BASE_URL", "http://127.0.0.1:8080")
DEFAULT_ROWS = int(os.environ.get("RHOKP_RAG_ROWS", "5"))


def retrieve(
    query: str,
    base_url: str = DEFAULT_BASE,
    rows: int = DEFAULT_ROWS,
) -> dict:
    """
    Retrieve relevant docs from the OKP search API for RAG context.

    Args:
        query: Search query string.
        base_url: OKP base URL (e.g. http://127.0.0.1:8080).
        rows: Maximum number of documents to return.

    Returns:
        Dict with keys: query, numFound, docs (list of {title, snippet, ...}),
        context (single string of numbered snippets for LLM prompts).
        On error, includes an "error" key.
    """
    path = "/solr/portal/select"
    params = {
        "q": query,
        "rows": rows,
        "wt": "json",
        "hl": "true",
        "hl.fl": "main_content,title",
        "hl.snippets": 2,
        "hl.fragsize": 300,
    }
    url = f"{base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read()[:500]
        details = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        return {"error": f"HTTP {e.code}", "details": details}
    except Exception as e:
        return {"error": str(e)}

    docs = data.get("response", {}).get("docs", [])
    highlighting = data.get("highlighting", {})

    out_docs = []
    for d in docs:
        resource = d.get("resourceName", "")
        hl = highlighting.get(resource, {}) if resource else {}
        snippet = (
            (hl.get("main_content") or [])[:1]
            or (hl.get("title") or [])
            or [d.get("title") or (d.get("main_content", "") or "")[:300]]
        )
        snippet = snippet[0][:500] if snippet else ""
        title = d.get("title", "")
        out_docs.append({
            "title": title,
            "snippet": snippet,
            "url_slug": d.get("url_slug", ""),
            "resourceName": resource,
            "documentKind": d.get("documentKind", ""),
        })

    context_parts = []
    for i, o in enumerate(out_docs, 1):
        context_parts.append(f"[{i}] {o['title']}\n{o['snippet']}")
    context = "\n\n".join(context_parts)

    return {
        "query": query,
        "numFound": data.get("response", {}).get("numFound", 0),
        "docs": out_docs,
        "context": context,
    }
