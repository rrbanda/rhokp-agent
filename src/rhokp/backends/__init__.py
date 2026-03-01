"""Pluggable search backends for rhokp.

The :class:`SearchBackend` protocol defines the contract that all backends
must satisfy.  The default implementation is :class:`SolrBackend` which
queries RHOKP's embedded Solr instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rhokp.models import FacetCounts, OKPDocument


@runtime_checkable
class SearchBackend(Protocol):
    """Protocol for search backends used by :class:`~rhokp.client.OKPClient`.

    Implementations must return a tuple of ``(docs, num_found, facets)``.
    """

    def search(
        self,
        query: str,
        rows: int,
        *,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[OKPDocument], int, FacetCounts]: ...

    async def asearch(
        self,
        query: str,
        rows: int,
        *,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[OKPDocument], int, FacetCounts]: ...


__all__ = ["SearchBackend"]
