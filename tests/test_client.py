"""Tests for rhokp.client -- OKPClient and module-level functions.

Uses httpx MockTransport so no real OKP or network is required.
"""

from __future__ import annotations

import json
import logging
import time

import httpx
import pytest

from rhokp.backends import SearchBackend
from rhokp.backends.mock import MockBackend
from rhokp.client import OKPClient, _CircuitBreaker, _backoff_delay, aretrieve, retrieve
from rhokp.config import OKPConfig
from rhokp.logging import JSONFormatter, bind_request_id, configure_logging, get_request_id
from rhokp.models import (
    OKPConnectionError,
    OKPDocument,
    OKPResponseError,
    OKPSearchError,
    RetrieveResult,
)


SOLR_SUCCESS = {
    "responseHeader": {"status": 0, "QTime": 10},
    "response": {
        "numFound": 2,
        "start": 0,
        "docs": [
            {
                "id": "/solutions/123/index.html",
                "resourceName": "/solutions/123/index.html",
                "title": "Install Guide",
                "url_slug": "123",
                "documentKind": "documentation",
                "main_content": "How to install the product.",
                "product": "OpenShift Container Platform",
                "documentation_version": "4.16",
                "score": 28.5,
                "lastModifiedDate": "2024-12-01T00:00:00Z",
                "view_uri": "/docs/install",
                "heading_h2": ["prerequisites", "steps"],
            },
            {
                "id": "/solutions/456/index.html",
                "resourceName": "/solutions/456/index.html",
                "title": "Upgrade Notes",
                "url_slug": "456",
                "documentKind": "solution",
                "main_content": "Steps to upgrade.",
                "product": "Red Hat Enterprise Linux",
                "documentation_version": "9.4",
                "score": 15.2,
                "lastModifiedDate": "2024-11-01T00:00:00Z",
            },
        ],
    },
    "highlighting": {
        "/solutions/123/index.html": {
            "main_content": ["How to <b>install</b> the product."],
            "title": ["<b>Install</b> Guide"],
        },
        "/solutions/456/index.html": {
            "main_content": ["Steps to <b>upgrade</b>."],
        },
    },
    "facet_counts": {
        "facet_fields": {
            "product": ["OpenShift Container Platform", 100, "Red Hat Enterprise Linux", 50],
            "documentKind": ["documentation", 80, "solution", 20],
            "documentation_version": ["4.16", 30, "9.4", 15],
        },
    },
}

SOLR_EMPTY = {
    "responseHeader": {"status": 0, "QTime": 1},
    "response": {"numFound": 0, "docs": []},
    "highlighting": {},
    "facet_counts": {"facet_fields": {}},
}


def _mock_handler(json_data: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json_data)

    return handler


class TestOKPClientSync:
    def _make_client(self, json_data: dict, status: int = 200) -> OKPClient:
        transport = httpx.MockTransport(_mock_handler(json_data, status))
        config = OKPConfig(base_url="http://okp:8080")
        return OKPClient(config, _sync_transport=transport)

    def test_success_returns_typed_result(self) -> None:
        with self._make_client(SOLR_SUCCESS) as client:
            result = client.retrieve("install")

        assert isinstance(result, RetrieveResult)
        assert result.query == "install"
        assert result.num_found == 2
        assert len(result.docs) == 2

    def test_doc_fields_populated(self) -> None:
        with self._make_client(SOLR_SUCCESS) as client:
            result = client.retrieve("install")

        doc = result.docs[0]
        assert isinstance(doc, OKPDocument)
        assert doc.title == "Install Guide"
        assert doc.product == "OpenShift Container Platform"
        assert doc.version == "4.16"
        assert doc.score == 28.5
        assert doc.document_kind == "documentation"
        assert doc.url_slug == "123"
        assert doc.headings == ["prerequisites", "steps"]

    def test_html_tags_stripped_from_snippets(self) -> None:
        with self._make_client(SOLR_SUCCESS) as client:
            result = client.retrieve("install")
        assert "<b>" not in result.docs[0].snippet
        assert "install" in result.docs[0].snippet

    def test_context_contains_numbered_entries_with_metadata(self) -> None:
        with self._make_client(SOLR_SUCCESS) as client:
            result = client.retrieve("install")
        assert "[1] Install Guide" in result.context
        assert "documentation" in result.context
        assert "OpenShift Container Platform" in result.context
        assert "Source: /123" in result.context

    def test_facets_parsed(self) -> None:
        with self._make_client(SOLR_SUCCESS) as client:
            result = client.retrieve("install")
        assert result.facets.products == {
            "OpenShift Container Platform": 100,
            "Red Hat Enterprise Linux": 50,
        }
        assert result.facets.document_kinds == {"documentation": 80, "solution": 20}
        assert result.facets.versions == {"4.16": 30, "9.4": 15}

    def test_empty_docs_returns_empty_context(self) -> None:
        with self._make_client(SOLR_EMPTY) as client:
            result = client.retrieve("nonexistent")
        assert result.num_found == 0
        assert result.docs == []
        assert result.context == ""

    def test_http_error_raises_search_error(self) -> None:
        with self._make_client({"error": "not found"}, status=503) as client:
            with pytest.raises(OKPSearchError, match="503"):
                client.retrieve("install")

    def test_connection_error_raises_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            with pytest.raises(OKPConnectionError, match="Cannot connect"):
                client.retrieve("install")

    def test_timeout_raises_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            with pytest.raises(OKPConnectionError, match="Timeout"):
                client.retrieve("install")

    def test_empty_query_raises_value_error(self) -> None:
        with self._make_client(SOLR_EMPTY) as client:
            with pytest.raises(ValueError, match="non-empty"):
                client.retrieve("")

    def test_whitespace_query_raises_value_error(self) -> None:
        with self._make_client(SOLR_EMPTY) as client:
            with pytest.raises(ValueError, match="non-empty"):
                client.retrieve("   ")

    def test_query_too_long_raises_value_error(self) -> None:
        config = OKPConfig(base_url="http://okp:8080", max_query_length=10)
        transport = httpx.MockTransport(_mock_handler(SOLR_EMPTY))
        with OKPClient(config, _sync_transport=transport) as client:
            with pytest.raises(ValueError, match="exceeds maximum"):
                client.retrieve("x" * 11)

    def test_env_fallback_for_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_BASE_URL", "http://from-env:9999")
        transport = httpx.MockTransport(_mock_handler(SOLR_EMPTY))
        result = retrieve("test", rows=1, _transport_override=transport)
        assert isinstance(result, RetrieveResult)

    def test_to_dict_serialization(self) -> None:
        with self._make_client(SOLR_SUCCESS) as client:
            result = client.retrieve("install")
        d = result.to_dict()
        assert d["query"] == "install"
        assert d["num_found"] == 2
        assert len(d["docs"]) == 2
        assert d["docs"][0]["product"] == "OpenShift Container Platform"

    def test_closed_client_raises(self) -> None:
        client = self._make_client(SOLR_EMPTY)
        client.close()
        with pytest.raises(RuntimeError, match="closed"):
            client.retrieve("test")

    def test_filter_params_sent(self) -> None:
        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(200, json=SOLR_EMPTY)

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            client.retrieve("install", product="OpenShift", version="4.16")

        assert len(requests_seen) == 1
        url = str(requests_seen[0].url)
        assert "product" in url or "fq" in url


class TestOKPClientAsync:
    async def test_async_success(self) -> None:
        transport = httpx.MockTransport(_mock_handler(SOLR_SUCCESS))
        config = OKPConfig(base_url="http://okp:8080")
        async with OKPClient(config, _async_transport=transport) as client:
            result = await client.aretrieve("install")
        assert isinstance(result, RetrieveResult)
        assert result.num_found == 2

    async def test_async_http_error(self) -> None:
        transport = httpx.MockTransport(_mock_handler({"error": "bad"}, status=500))
        config = OKPConfig(base_url="http://okp:8080")
        async with OKPClient(config, _async_transport=transport) as client:
            with pytest.raises(OKPSearchError, match="500"):
                await client.aretrieve("install")

    async def test_async_empty_query(self) -> None:
        transport = httpx.MockTransport(_mock_handler(SOLR_EMPTY))
        config = OKPConfig(base_url="http://okp:8080")
        async with OKPClient(config, _async_transport=transport) as client:
            with pytest.raises(ValueError, match="non-empty"):
                await client.aretrieve("")


class TestParseResponseEdgeCases:
    """Test defensive parsing of malformed Solr responses."""

    def _retrieve_with_data(self, data: dict) -> RetrieveResult:
        transport = httpx.MockTransport(_mock_handler(data))
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            return client.retrieve("test")

    def test_missing_response_key(self) -> None:
        with pytest.raises(OKPResponseError, match="Expected 'response' dict"):
            self._retrieve_with_data({"no_response": True})

    def test_response_is_string(self) -> None:
        with pytest.raises(OKPResponseError):
            self._retrieve_with_data({"response": "not a dict"})

    def test_docs_contains_non_dict(self) -> None:
        data = {
            "response": {"numFound": 1, "docs": ["not-a-dict", 42]},
            "highlighting": {},
        }
        result = self._retrieve_with_data(data)
        assert result.docs == []

    def test_missing_highlighting(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [{"title": "T", "resourceName": "r", "documentKind": "d"}],
            },
        }
        result = self._retrieve_with_data(data)
        assert len(result.docs) == 1
        assert result.docs[0].title == "T"

    def test_highlighting_wrong_type(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [{"title": "T", "id": "r1", "resourceName": "r1"}],
            },
            "highlighting": "not-a-dict",
        }
        result = self._retrieve_with_data(data)
        assert len(result.docs) == 1

    def test_numfound_wrong_type(self) -> None:
        data = {
            "response": {"numFound": "not-an-int", "docs": []},
        }
        result = self._retrieve_with_data(data)
        assert result.num_found == 0

    def test_empty_facet_counts(self) -> None:
        data = {
            "response": {"numFound": 0, "docs": []},
            "facet_counts": {},
        }
        result = self._retrieve_with_data(data)
        assert result.facets.products == {}

    def test_unicode_in_title(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [{"title": "Red Hat\u2019s Guide", "resourceName": "r1"}],
            },
        }
        result = self._retrieve_with_data(data)
        assert "\u2019" in result.docs[0].title

    def test_html_entities_in_highlighting(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [{"title": "Test", "id": "r1", "resourceName": "r1"}],
            },
            "highlighting": {
                "r1": {"main_content": ["it&#x27;s <b>highlighted</b> &amp; decoded"]},
            },
        }
        result = self._retrieve_with_data(data)
        assert "it's" in result.docs[0].snippet
        assert "highlighted" in result.docs[0].snippet
        assert "&" in result.docs[0].snippet
        assert "<b>" not in result.docs[0].snippet


class TestCVEErrataFields:
    """Test parsing of CVE/errata-specific fields."""

    def _retrieve_with_data(self, data: dict) -> RetrieveResult:
        transport = httpx.MockTransport(_mock_handler(data))
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            return client.retrieve("test")

    def test_severity_from_portal_severity(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "title": "RHSA-2024:1234",
                        "resourceName": "r1",
                        "documentKind": "errata",
                        "portal_severity": "Important",
                        "portal_advisory_type": "RHSA",
                        "portal_synopsis": "Critical kernel update",
                    }
                ],
            },
        }
        result = self._retrieve_with_data(data)
        assert result.docs[0].severity == "Important"
        assert result.docs[0].advisory_type == "RHSA"
        assert result.docs[0].synopsis == "Critical kernel update"

    def test_severity_from_cve_threat_severity(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "title": "CVE-2024-5678",
                        "resourceName": "r1",
                        "documentKind": "cve",
                        "cve_threatSeverity": "Critical",
                    }
                ],
            },
        }
        result = self._retrieve_with_data(data)
        assert result.docs[0].severity == "Critical"

    def test_severity_context_includes_severity_tag(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [
                    {
                        "title": "RHSA-2024:1234",
                        "resourceName": "r1",
                        "url_slug": "errata/RHSA-2024:1234",
                        "documentKind": "errata",
                        "portal_severity": "Important",
                        "portal_advisory_type": "RHSA",
                        "portal_synopsis": "Kernel security update",
                        "main_content": "Updated kernel packages fix a bug.",
                    }
                ],
            },
        }
        result = self._retrieve_with_data(data)
        assert "[Important]" in result.context

    def test_missing_cve_fields_default_empty(self) -> None:
        data = {
            "response": {
                "numFound": 1,
                "docs": [{"title": "Plain doc", "resourceName": "r1", "documentKind": "guide"}],
            },
        }
        result = self._retrieve_with_data(data)
        assert result.docs[0].severity == ""
        assert result.docs[0].advisory_type == ""
        assert result.docs[0].synopsis == ""

    def test_content_subtype_facet_parsed(self) -> None:
        data = {
            "response": {"numFound": 0, "docs": []},
            "facet_counts": {
                "facet_fields": {
                    "portal_content_subtype": ["article", 50, "solution", 30],
                },
            },
        }
        result = self._retrieve_with_data(data)
        assert result.facets.content_subtypes == {"article": 50, "solution": 30}


class TestOKPClientHealthCheck:
    def test_healthy(self) -> None:
        transport = httpx.MockTransport(_mock_handler(SOLR_SUCCESS))
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            health = client.check_health()
        assert health["status"] == "healthy"
        assert health["num_indexed"] == 2
        assert "products_available" in health
        assert "solr_handler" in health

    def test_unhealthy(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(handler)
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, _sync_transport=transport) as client:
            health = client.check_health()
        assert health["status"] == "unhealthy"
        assert "error" in health


class TestSolrHandlerConfig:
    def test_custom_handler_path(self) -> None:
        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(200, json=SOLR_EMPTY)

        transport = httpx.MockTransport(handler)
        config = OKPConfig(
            base_url="http://okp:8080",
            solr_handler="/solr/portal/select-errata",
        )
        with OKPClient(config, _sync_transport=transport) as client:
            client.retrieve("CVE-2024-1234")

        assert len(requests_seen) == 1
        assert "/select-errata" in str(requests_seen[0].url)


class TestModuleLevelFunctions:
    def test_retrieve_convenience(self) -> None:
        transport = httpx.MockTransport(_mock_handler(SOLR_SUCCESS))
        result = retrieve(
            "install",
            base_url="http://okp:8080",
            rows=5,
            _transport_override=transport,
        )
        assert isinstance(result, RetrieveResult)
        assert result.num_found == 2

    async def test_aretrieve_convenience(self) -> None:
        transport = httpx.MockTransport(_mock_handler(SOLR_SUCCESS))
        result = await aretrieve(
            "install",
            base_url="http://okp:8080",
            rows=5,
            _transport_override=transport,
        )
        assert isinstance(result, RetrieveResult)
        assert result.num_found == 2


# ---------------------------------------------------------------------------
# Priority 1 tests: structured logging, caching, circuit breaker, backoff,
# token-budget context
# ---------------------------------------------------------------------------


class TestJSONLogging:
    def test_json_formatter_output(self) -> None:
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="rhokp.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "rhokp.test"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed

    def test_json_formatter_with_exception(self) -> None:
        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="rhokp.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="fail",
            args=(),
            exc_info=exc_info,
        )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert "exception" in parsed
        assert "boom" in parsed["exception"]

    def test_json_formatter_includes_request_id(self) -> None:
        rid = bind_request_id("test-req-42")
        assert rid == "test-req-42"
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="rhokp.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="with rid",
            args=(),
            exc_info=None,
        )
        record.request_id = rid  # type: ignore[attr-defined]
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["request_id"] == "test-req-42"

    def test_json_formatter_extras_merged(self) -> None:
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="rhokp.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="extra",
            args=(),
            exc_info=None,
        )
        record.tool = "search_red_hat_docs"  # type: ignore[attr-defined]
        record.elapsed_ms = 42.5  # type: ignore[attr-defined]
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["tool"] == "search_red_hat_docs"
        assert parsed["elapsed_ms"] == 42.5

    def test_json_formatter_no_request_id_when_unbound(self) -> None:
        from rhokp.logging import _request_id_var

        token = _request_id_var.set("")
        try:
            fmt = JSONFormatter()
            record = logging.LogRecord(
                name="rhokp.test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="no rid",
                args=(),
                exc_info=None,
            )
            line = fmt.format(record)
            parsed = json.loads(line)
            assert "request_id" not in parsed
        finally:
            _request_id_var.reset(token)

    def test_bind_request_id_generates_uuid(self) -> None:
        rid = bind_request_id()
        assert len(rid) == 12
        assert get_request_id() == rid

    def test_bind_request_id_explicit(self) -> None:
        rid = bind_request_id("my-custom-id")
        assert rid == "my-custom-id"
        assert get_request_id() == "my-custom-id"

    def test_configure_logging_sets_json(self) -> None:
        configure_logging(json_format=True)
        logger = logging.getLogger("rhokp")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_configure_logging_text(self) -> None:
        configure_logging(json_format=False)
        logger = logging.getLogger("rhokp")
        assert len(logger.handlers) == 1
        assert not isinstance(logger.handlers[0].formatter, JSONFormatter)


class TestResponseCache:
    def _make_client(
        self, json_data: dict, *, cache_ttl: float = 60.0, cache_max_entries: int = 256
    ) -> tuple[OKPClient, list[httpx.Request]]:
        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(200, json=json_data)

        transport = httpx.MockTransport(handler)
        config = OKPConfig(
            base_url="http://okp:8080",
            cache_ttl=cache_ttl,
            cache_max_entries=cache_max_entries,
        )
        return OKPClient(config, _sync_transport=transport), requests_seen

    def test_cache_hit(self) -> None:
        client, reqs = self._make_client(SOLR_SUCCESS)
        with client:
            r1 = client.retrieve("install")
            r2 = client.retrieve("install")
        assert len(reqs) == 1
        assert r1.query == r2.query

    def test_cache_miss_different_query(self) -> None:
        client, reqs = self._make_client(SOLR_SUCCESS)
        with client:
            client.retrieve("install")
            client.retrieve("upgrade")
        assert len(reqs) == 2

    def test_cache_miss_different_params(self) -> None:
        client, reqs = self._make_client(SOLR_SUCCESS)
        with client:
            client.retrieve("install", product="RHEL")
            client.retrieve("install", product="OCP")
        assert len(reqs) == 2

    def test_cache_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, reqs = self._make_client(SOLR_SUCCESS, cache_ttl=0.01)
        with client:
            client.retrieve("install")
            time.sleep(0.02)
            client.retrieve("install")
        assert len(reqs) == 2

    def test_cache_eviction(self) -> None:
        client, reqs = self._make_client(SOLR_SUCCESS, cache_max_entries=2)
        with client:
            client.retrieve("a")
            client.retrieve("b")
            client.retrieve("c")  # evicts "a"
            client.retrieve("a")  # must miss
        assert len(reqs) == 4

    def test_cache_disabled_by_default(self) -> None:
        config = OKPConfig(base_url="http://okp:8080")
        assert config.cache_ttl == 0.0

    def test_clear_cache(self) -> None:
        client, reqs = self._make_client(SOLR_SUCCESS)
        with client:
            client.retrieve("install")
            client.clear_cache()
            client.retrieve("install")
        assert len(reqs) == 2


class TestCircuitBreaker:
    def test_closed_by_default(self) -> None:
        cb = _CircuitBreaker(failure_threshold=3, reset_timeout=30.0)
        assert cb.state == _CircuitBreaker.CLOSED
        cb.check()  # should not raise

    def test_opens_after_threshold(self) -> None:
        cb = _CircuitBreaker(failure_threshold=2, reset_timeout=30.0)
        cb.record_failure()
        cb.check()  # still closed
        cb.record_failure()
        with pytest.raises(OKPConnectionError, match="Circuit breaker is open"):
            cb.check()

    def test_half_open_after_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cb = _CircuitBreaker(failure_threshold=1, reset_timeout=0.01)
        cb.record_failure()
        assert cb.state == _CircuitBreaker.OPEN
        time.sleep(0.02)
        cb.check()  # should transition to half_open
        assert cb.state == _CircuitBreaker.HALF_OPEN

    def test_success_resets_to_closed(self) -> None:
        cb = _CircuitBreaker(failure_threshold=1, reset_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.check()  # half_open
        cb.record_success()
        assert cb.state == _CircuitBreaker.CLOSED

    def test_disabled_when_threshold_zero(self) -> None:
        cb = _CircuitBreaker(failure_threshold=0, reset_timeout=30.0)
        for _ in range(100):
            cb.record_failure()
        cb.check()  # should not raise

    def test_client_circuit_breaker_integration(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(handler)
        config = OKPConfig(
            base_url="http://okp:8080",
            circuit_failure_threshold=2,
            circuit_reset_timeout=60.0,
        )
        with OKPClient(config, _sync_transport=transport) as client:
            with pytest.raises(OKPConnectionError):
                client.retrieve("test1")
            with pytest.raises(OKPConnectionError):
                client.retrieve("test2")
            # Now circuit is open -- should fail fast without making HTTP call
            with pytest.raises(OKPConnectionError, match="Circuit breaker"):
                client.retrieve("test3")
        assert call_count == 2


class TestExponentialBackoff:
    def test_backoff_delay_formula(self) -> None:
        assert _backoff_delay(0, 0.5, 8.0) == 0.5
        assert _backoff_delay(1, 0.5, 8.0) == 1.0
        assert _backoff_delay(2, 0.5, 8.0) == 2.0
        assert _backoff_delay(3, 0.5, 8.0) == 4.0
        assert _backoff_delay(4, 0.5, 8.0) == 8.0
        assert _backoff_delay(5, 0.5, 8.0) == 8.0  # capped

    def test_retry_on_503(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(503, json={"error": "overloaded"})
            return httpx.Response(200, json=SOLR_SUCCESS)

        transport = httpx.MockTransport(handler)
        config = OKPConfig(
            base_url="http://okp:8080",
            retry_max_attempts=3,
            retry_backoff_base=0.01,
            retry_backoff_max=0.02,
        )
        with OKPClient(config, _sync_transport=transport) as client:
            result = client.retrieve("install")
        assert call_count == 3
        assert result.num_found == 2

    def test_no_retry_on_400(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, json={"error": "bad request"})

        transport = httpx.MockTransport(handler)
        config = OKPConfig(
            base_url="http://okp:8080",
            retry_max_attempts=3,
            retry_backoff_base=0.01,
        )
        with OKPClient(config, _sync_transport=transport) as client:
            with pytest.raises(OKPSearchError, match="400"):
                client.retrieve("install")
        assert call_count == 1

    def test_retry_exhaustion(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(429, json={"error": "rate limited"})

        transport = httpx.MockTransport(handler)
        config = OKPConfig(
            base_url="http://okp:8080",
            retry_max_attempts=2,
            retry_backoff_base=0.01,
            retry_backoff_max=0.02,
        )
        with OKPClient(config, _sync_transport=transport) as client:
            with pytest.raises(OKPSearchError, match="429"):
                client.retrieve("install")
        assert call_count == 3  # 1 initial + 2 retries

    def test_disabled_by_default(self) -> None:
        config = OKPConfig(base_url="http://okp:8080")
        assert config.retry_max_attempts == 0


class TestTokenBudgetContext:
    def _retrieve_with_budget(
        self, max_context_chars: int, json_data: dict | None = None
    ) -> RetrieveResult:
        transport = httpx.MockTransport(_mock_handler(json_data or SOLR_SUCCESS))
        config = OKPConfig(
            base_url="http://okp:8080",
            max_context_chars=max_context_chars,
        )
        with OKPClient(config, _sync_transport=transport) as client:
            return client.retrieve("install")

    def test_unlimited_by_default(self) -> None:
        result = self._retrieve_with_budget(0)
        assert len(result.docs) == 2
        assert "[1]" in result.context
        assert "[2]" in result.context

    def test_budget_truncates(self) -> None:
        result_full = self._retrieve_with_budget(0)
        result_short = self._retrieve_with_budget(50)
        assert len(result_short.context) <= len(result_full.context)
        assert "[1]" in result_short.context

    def test_budget_always_includes_first_entry(self) -> None:
        result = self._retrieve_with_budget(1)
        assert "[1]" in result.context
        assert "[2]" not in result.context

    def test_config_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_MAX_CONTEXT_CHARS", "500")
        config = OKPConfig.from_env()
        assert config.max_context_chars == 500


class TestSearchBackendProtocol:
    def test_mock_backend_satisfies_protocol(self) -> None:
        backend = MockBackend()
        assert isinstance(backend, SearchBackend)

    def test_client_with_mock_backend(self) -> None:
        docs = [
            OKPDocument(
                title="Mock Doc",
                snippet="mock content",
                url_slug="mock/123",
                resource_name="r1",
                document_kind="solution",
            )
        ]
        backend = MockBackend(docs=docs, num_found=1)
        config = OKPConfig(base_url="http://okp:8080")
        with OKPClient(config, backend=backend) as client:
            result = client.retrieve("test query")
        assert result.num_found == 1
        assert result.docs[0].title == "Mock Doc"
        assert "Mock Doc" in result.context
        assert backend.queries == ["test query"]

    async def test_client_async_with_mock_backend(self) -> None:
        docs = [
            OKPDocument(
                title="Async Mock",
                snippet="async content",
                url_slug="mock/456",
                resource_name="r2",
                document_kind="documentation",
            )
        ]
        backend = MockBackend(docs=docs, num_found=1)
        config = OKPConfig(base_url="http://okp:8080")
        async with OKPClient(config, backend=backend) as client:
            result = await client.aretrieve("async test")
        assert result.num_found == 1
        assert result.docs[0].title == "Async Mock"
