"""Google Agent Development Kit (ADK) tool adapter for RHOKP.

Provides a :class:`SearchRedHatDocs` tool that wraps :class:`~rhokp.client.OKPClient`
for use with Google ADK agents.

Requires the ``google-adk`` package::

    pip install rhokp[adk]
"""

from __future__ import annotations

from typing import Any

try:
    from google.adk.tools import FunctionTool
except ImportError as _exc:
    raise ImportError(
        "google-adk is required for the ADK adapter. Install it with: pip install rhokp[adk]"
    ) from _exc

from rhokp.client import OKPClient
from rhokp.config import OKPConfig


def _search_red_hat_docs(
    query: str,
    rows: int = 5,
    product: str | None = None,
    version: str | None = None,
    document_kind: str | None = None,
) -> dict[str, Any]:
    """Search Red Hat Offline Knowledge Portal for documentation, solutions, CVEs, and errata.

    Args:
        query: Search query describing what you're looking for.
        rows: Maximum number of results to return (1-100, default 5).
        product: Filter by Red Hat product name (e.g. "OpenShift Container Platform").
        version: Filter by product version (e.g. "4.16").
        document_kind: Filter by content type ("documentation", "solution", "cve", "errata").

    Returns:
        Dictionary with query results including documents, context, and facets.
    """
    config = OKPConfig.from_env()
    with OKPClient(config) as client:
        result = client.retrieve(
            query,
            rows=rows,
            product=product,
            version=version,
            document_kind=document_kind,
        )
    return result.to_dict()


search_red_hat_docs = FunctionTool(func=_search_red_hat_docs)

__all__ = ["search_red_hat_docs"]
