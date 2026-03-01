"""
MCP server exposing OKP search as a tool for Llama Stack and other MCP clients.

Uses FastMCP (https://gofastmcp.com). Run with:
    python -m rhokp.mcp.server
    # or via entry point: rhokp-mcp

Environment:
    RHOKP_BASE_URL       OKP base URL (default http://127.0.0.1:8080)
    RHOKP_SOLR_HANDLER   Solr handler path (default /solr/portal/select)
    RHOKP_RAG_ROWS       Max docs to return (default 5)
    RHOKP_TIMEOUT_READ   Read timeout seconds (default 25.0)
    MCP_PORT             Server port (default 8010)
    MCP_HOST             Server host (default 0.0.0.0)
"""

from __future__ import annotations

import json
import logging
import os

from fastmcp import Context, FastMCP
from fastmcp.server.lifespan import lifespan
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from mcp.types import ToolAnnotations

from rhokp import OKPClient, OKPConfig, OKPError
from rhokp.logging import bind_request_id

logger = logging.getLogger(__name__)


@lifespan
async def okp_lifespan(server: FastMCP) -> dict:  # type: ignore[type-arg]
    """Initialize OKPClient at startup and close it on shutdown."""
    config = OKPConfig.from_env()
    client = OKPClient(config)
    logger.info(
        "OKP client initialized: %s%s",
        config.base_url,
        config.solr_handler,
    )

    products: list[str] = []
    try:
        result = await client.aretrieve("test", rows=1)
        products = sorted(result.facets.products.keys())
        logger.info("Loaded %d product names for filter resolution", len(products))
    except Exception:
        logger.warning("Could not load product list; product filters will use exact match")

    try:
        yield {"client": client, "config": config, "products": products}
    finally:
        await client.aclose()
        logger.info("OKP client closed")


mcp = FastMCP("OKP Search", lifespan=okp_lifespan)

mcp.add_middleware(
    LoggingMiddleware(
        logger=logging.getLogger("rhokp.mcp.middleware"),
        include_payload_length=True,
    )
)
mcp.add_middleware(
    ErrorHandlingMiddleware(
        include_traceback=False,
        transform_errors=True,
    )
)


def _bind_mcp_request_id(ctx: Context | None) -> None:
    """Bridge FastMCP's request_id into our logging context-var."""
    if ctx is not None and ctx.request_context is not None:
        bind_request_id(str(ctx.request_context.request_id))
    else:
        bind_request_id()


def _resolve_product(name: str, known_products: list[str]) -> str:
    """Resolve an approximate product name to the exact indexed name.

    Handles common LLM behaviors like omitting the "Red Hat" prefix or using
    shortened names. Returns the original name if no match is found.
    """
    if not name or not known_products:
        return name

    name_lower = name.strip().lower()

    for p in known_products:
        if p.lower() == name_lower:
            return p

    words = name_lower.split()
    candidates = [p for p in known_products if all(w in p.lower() for w in words)]

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:

        def _overlap(product: str) -> float:
            pw = product.lower().split()
            return sum(1 for w in words if w in pw) / len(pw) if pw else 0.0

        best = max(candidates, key=_overlap)
        logger.debug(
            "Multiple product matches for %r: %s -> picking %r",
            name,
            [c for c in candidates],
            best,
        )
        return best

    for p in known_products:
        if name_lower in p.lower():
            return p

    return name


_SEARCH_ANNOTATIONS = ToolAnnotations(
    title="Search Red Hat Documentation",
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

_HEALTH_ANNOTATIONS = ToolAnnotations(
    title="Check OKP Health",
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(annotations=_SEARCH_ANNOTATIONS)
async def search_red_hat_docs(
    query: str,
    ctx: Context,
    product: str | None = None,
    version: str | None = None,
    document_kind: str | None = None,
    max_results: int = 5,
) -> str:
    """Search Red Hat Offline Knowledge Portal for official product documentation.

    Returns numbered documentation excerpts with source references. Results are
    matched using the portal's tuned search (edismax with field boosting and
    phrase matching). For best results, use specific product terminology.

    Only use this tool for questions about Red Hat products (OpenShift, RHEL,
    Ansible, etc.). Do not use for general programming or non-Red-Hat topics.

    Args:
        query: Search terms (e.g. 'OpenShift 4.16 bare metal install',
               'RHEL 9 kernel tuning parameters')
        product: Optional product filter. Use the full official name
                 (e.g. 'OpenShift Container Platform',
                 'Red Hat Enterprise Linux',
                 'Red Hat Ansible Automation Platform').
                 Partial names are resolved automatically.
                 Omit to search all products.
        version: Optional version filter (e.g. '4.16', '9.4'). Omit to search
                 all versions.
        document_kind: Optional document type filter (e.g. 'documentation',
                       'solution', 'errata'). Omit to search all types.
        max_results: Maximum number of documentation excerpts to return (1-20).
    """
    _bind_mcp_request_id(ctx)
    rows = max(1, min(max_results, 20))
    client: OKPClient = ctx.lifespan_context["client"]
    known_products: list[str] = ctx.lifespan_context.get("products", [])

    resolved_product = _resolve_product(product, known_products) if product else None
    if resolved_product and resolved_product != product:
        logger.info("Product filter resolved: %r -> %r", product, resolved_product)

    try:
        result = await client.aretrieve(
            query,
            rows=rows,
            product=resolved_product,
            version=version,
            document_kind=document_kind,
        )
    except OKPError as exc:
        logger.warning("OKP search error for query=%r: %s", query, exc)
        return json.dumps({"error": str(exc), "num_found": 0, "docs": []})
    except ValueError as exc:
        logger.warning("Invalid query=%r: %s", query, exc)
        return json.dumps({"error": str(exc), "num_found": 0, "docs": []})

    if not result.docs:
        return json.dumps({"num_found": 0, "docs": [], "context": "No results found."})

    response: dict = {
        "num_found": result.num_found,
        "context": result.context,
        "docs": [
            {
                "title": doc.title,
                "kind": doc.document_kind,
                "product": doc.product,
                "version": doc.version,
                "source": doc.view_uri or (f"/{doc.url_slug}" if doc.url_slug else ""),
            }
            for doc in result.docs
        ],
    }
    return json.dumps(response)


@mcp.tool(annotations=_HEALTH_ANNOTATIONS)
async def check_okp_health(ctx: Context) -> str:
    """Check if the OKP search backend is reachable and responding.

    Returns status information including the number of indexed documents,
    the configured base URL, and the Solr handler in use.
    """
    _bind_mcp_request_id(ctx)
    client: OKPClient = ctx.lifespan_context["client"]
    config: OKPConfig = ctx.lifespan_context["config"]

    try:
        result = await client.aretrieve("test", rows=1)
        info: dict = {
            "status": "healthy",
            "num_indexed": result.num_found,
            "base_url": config.base_url,
            "solr_handler": config.solr_handler,
        }
        if result.facets.products:
            info["products_available"] = len(result.facets.products)
        return json.dumps(info)
    except OKPError as exc:
        return json.dumps(
            {
                "status": "unhealthy",
                "error": str(exc),
                "base_url": config.base_url,
            }
        )


def main() -> None:
    from rhokp.logging import configure_logging

    configure_logging(json_format=True)

    fastmcp_root = logging.getLogger("fastmcp")
    rhokp_root = logging.getLogger("rhokp")
    if rhokp_root.handlers:
        fastmcp_root.handlers = list(rhokp_root.handlers)
        fastmcp_root.filters = list(rhokp_root.filters)
        fastmcp_root.setLevel(rhokp_root.level)
        fastmcp_root.propagate = False

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("MCP_PORT", "8010"))
    except ValueError:
        logger.error("MCP_PORT must be a valid integer")
        raise SystemExit(1)

    logger.info("Starting OKP MCP server on %s:%d", host, port)
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
