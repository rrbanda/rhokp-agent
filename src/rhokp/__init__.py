"""rhokp: Red Hat Offline Knowledge Portal retrieval for RAG and AI agents."""

from rhokp.client import OKPClient, aretrieve, retrieve
from rhokp.config import OKPConfig
from rhokp.logging import bind_request_id, configure_logging, get_request_id
from rhokp.models import (
    FacetCounts,
    OKPConnectionError,
    OKPDocument,
    OKPError,
    OKPResponseError,
    OKPSearchError,
    RetrieveResult,
)

__version__ = "0.5.0"

__all__ = [
    "OKPClient",
    "OKPConfig",
    "FacetCounts",
    "OKPConnectionError",
    "OKPDocument",
    "OKPError",
    "OKPResponseError",
    "OKPSearchError",
    "RetrieveResult",
    "__version__",
    "aretrieve",
    "bind_request_id",
    "configure_logging",
    "get_request_id",
    "retrieve",
]
