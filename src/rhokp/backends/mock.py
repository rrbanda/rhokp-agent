"""In-memory mock backend for testing without network access."""

from __future__ import annotations

from rhokp.models import FacetCounts, OKPDocument


class MockBackend:
    """A :class:`~rhokp.backends.SearchBackend` that returns canned results.

    Useful for unit tests and offline development.

    Usage::

        backend = MockBackend(docs=[OKPDocument(title="Test", ...)])
        docs, num_found, facets = backend.search("anything", rows=5)
    """

    def __init__(
        self,
        docs: list[OKPDocument] | None = None,
        num_found: int | None = None,
        facets: FacetCounts | None = None,
    ) -> None:
        self._docs = docs or []
        self._num_found = num_found if num_found is not None else len(self._docs)
        self._facets = facets or FacetCounts()
        self.queries: list[str] = []

    def search(
        self,
        query: str,
        rows: int,
        *,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[OKPDocument], int, FacetCounts]:
        self.queries.append(query)
        return self._docs[:rows], self._num_found, self._facets

    async def asearch(
        self,
        query: str,
        rows: int,
        *,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[OKPDocument], int, FacetCounts]:
        self.queries.append(query)
        return self._docs[:rows], self._num_found, self._facets
