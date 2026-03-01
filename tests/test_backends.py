"""Tests for rhokp.backends -- SearchBackend protocol and implementations."""

from __future__ import annotations

import httpx
import pytest

from rhokp.backends import SearchBackend
from rhokp.backends.mock import MockBackend
from rhokp.backends.solr import SolrBackend
from rhokp.config import OKPConfig
from rhokp.models import FacetCounts, OKPConnectionError, OKPDocument, OKPSearchError


SOLR_RESPONSE = {
    "responseHeader": {"status": 0, "QTime": 5},
    "response": {
        "numFound": 1,
        "docs": [
            {
                "title": "Test Doc",
                "resourceName": "r1",
                "url_slug": "test/1",
                "documentKind": "solution",
                "main_content": "Test content",
                "product": "RHEL",
            },
        ],
    },
    "highlighting": {},
    "facet_counts": {"facet_fields": {}},
}


class TestMockBackend:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(MockBackend(), SearchBackend)

    def test_returns_canned_docs(self) -> None:
        doc = OKPDocument(
            title="T", snippet="S", url_slug="u", resource_name="r", document_kind="d"
        )
        backend = MockBackend(docs=[doc], num_found=1)
        docs, num, facets = backend.search("q", 5)
        assert len(docs) == 1
        assert num == 1
        assert isinstance(facets, FacetCounts)

    def test_records_queries(self) -> None:
        backend = MockBackend()
        backend.search("a", 5)
        backend.search("b", 5)
        assert backend.queries == ["a", "b"]

    def test_respects_rows(self) -> None:
        docs = [
            OKPDocument(
                title=f"D{i}", snippet="s", url_slug="u", resource_name=f"r{i}", document_kind="d"
            )
            for i in range(10)
        ]
        backend = MockBackend(docs=docs, num_found=10)
        result_docs, _, _ = backend.search("q", 3)
        assert len(result_docs) == 3

    async def test_async_search(self) -> None:
        backend = MockBackend()
        docs, num, facets = await backend.asearch("q", 5)
        assert docs == []
        assert num == 0


class TestSolrBackend:
    def _make_backend(self, json_data: dict, status: int = 200) -> SolrBackend:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json=json_data)

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        return SolrBackend(config, _sync_transport=transport)

    def test_satisfies_protocol(self) -> None:
        backend = self._make_backend(SOLR_RESPONSE)
        assert isinstance(backend, SearchBackend)

    def test_search_returns_docs(self) -> None:
        with self._make_backend(SOLR_RESPONSE) as backend:
            docs, num_found, facets = backend.search("test", 5)
        assert len(docs) == 1
        assert docs[0].title == "Test Doc"
        assert num_found == 1

    def test_search_with_filters(self) -> None:
        with self._make_backend(SOLR_RESPONSE) as backend:
            docs, _, _ = backend.search(
                "test", 5, product="RHEL", version="9", document_kind="solution"
            )
        assert len(docs) == 1

    def test_http_error_raises(self) -> None:
        with self._make_backend({"error": "bad"}, status=500) as backend:
            with pytest.raises(OKPSearchError, match="500"):
                backend.search("test", 5)

    def test_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        with SolrBackend(config, _sync_transport=transport) as backend:
            with pytest.raises(OKPConnectionError, match="Cannot connect"):
                backend.search("test", 5)

    async def test_async_search(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SOLR_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        async with SolrBackend(config, _async_transport=transport) as backend:
            docs, num_found, _ = await backend.asearch("test", 5)
        assert len(docs) == 1
        assert num_found == 1
