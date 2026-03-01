"""Tests for the MCP server's tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from rhokp.config import OKPConfig
from rhokp.models import (
    FacetCounts,
    OKPConnectionError,
    OKPDocument,
    OKPSearchError,
    RetrieveResult,
)

try:
    from rhokp.mcp.server import (
        _HEALTH_ANNOTATIONS,
        _SEARCH_ANNOTATIONS,
        _resolve_product,
        check_okp_health,
        mcp,
        search_red_hat_docs,
    )
except ImportError:
    pytest.skip("MCP server not importable (missing fastmcp)", allow_module_level=True)


FAKE_RESULT = RetrieveResult(
    query="openshift install",
    num_found=1,
    docs=[
        OKPDocument(
            title="Install Guide",
            snippet="How to install OpenShift.",
            url_slug="install",
            resource_name="r1",
            document_kind="documentation",
            product="OpenShift Container Platform",
            version="4.16",
            score=28.5,
            view_uri="/docs/install",
        )
    ],
    context=(
        "[1] Install Guide (documentation, OpenShift Container Platform, v4.16)\n"
        "How to install OpenShift.\n"
        "Source: /install"
    ),
    facets=FacetCounts(products={"OpenShift Container Platform": 100}),
)

EMPTY_RESULT = RetrieveResult(
    query="nonexistent",
    num_found=0,
    docs=[],
    context="",
)


KNOWN_PRODUCTS = [
    "OpenShift Container Platform",
    "Red Hat Advanced Cluster Security for Kubernetes",
    "Red Hat Ansible Automation Platform",
    "Red Hat Enterprise Linux",
    "Red Hat OpenShift Data Foundation",
    "Red Hat OpenShift GitOps",
    "Red Hat Satellite",
]


def _mock_ctx(
    client: AsyncMock | None = None,
    config: OKPConfig | None = None,
    products: list[str] | None = None,
) -> MagicMock:
    """Create a mock FastMCP Context with lifespan_context."""
    ctx = MagicMock()
    ctx.request_context = None
    ctx.lifespan_context = {
        "client": client or AsyncMock(),
        "config": config or OKPConfig(),
        "products": products if products is not None else KNOWN_PRODUCTS,
    }
    return ctx


class TestSearchRedHatDocs:
    async def test_success_returns_structured_json(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = FAKE_RESULT
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("openshift install", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["num_found"] == 1
        assert "[1] Install Guide" in parsed["context"]
        assert len(parsed["docs"]) == 1
        assert parsed["docs"][0]["title"] == "Install Guide"
        assert parsed["docs"][0]["kind"] == "documentation"

    async def test_response_includes_version_and_view_uri(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = FAKE_RESULT
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("openshift install", ctx=ctx)

        parsed = json.loads(result)
        doc = parsed["docs"][0]
        assert doc["version"] == "4.16"
        assert doc["source"] == "/docs/install"

    async def test_source_falls_back_to_url_slug(self) -> None:
        no_view_uri_result = RetrieveResult(
            query="test",
            num_found=1,
            docs=[
                OKPDocument(
                    title="Test",
                    snippet="snippet",
                    url_slug="test-slug",
                    resource_name="r1",
                    document_kind="documentation",
                    view_uri="",
                )
            ],
            context="[1] Test\nsnippet",
        )
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = no_view_uri_result
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("test", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["docs"][0]["source"] == "/test-slug"

    async def test_empty_results(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("nonexistent", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["num_found"] == 0
        assert parsed["context"] == "No results found."

    async def test_okp_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.side_effect = OKPConnectionError("unreachable")
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("openshift", ctx=ctx)

        parsed = json.loads(result)
        assert "error" in parsed
        assert "unreachable" in parsed["error"]

    async def test_okp_search_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.side_effect = OKPSearchError(503, "Service Unavailable")
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("openshift", ctx=ctx)

        parsed = json.loads(result)
        assert "error" in parsed
        assert "503" in parsed["error"]

    async def test_invalid_query(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.side_effect = ValueError("query must be a non-empty string")
        ctx = _mock_ctx(client=mock_client)

        result = await search_red_hat_docs("", ctx=ctx)

        parsed = json.loads(result)
        assert "error" in parsed

    async def test_max_results_clamped(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        await search_red_hat_docs("test", ctx=ctx, max_results=50)

        mock_client.aretrieve.assert_called_once()
        call_kwargs = mock_client.aretrieve.call_args
        assert call_kwargs.kwargs.get("rows") == 20

    async def test_version_filter_passed_through(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        await search_red_hat_docs("test", ctx=ctx, version="4.16")

        call_kwargs = mock_client.aretrieve.call_args
        assert call_kwargs.kwargs.get("version") == "4.16"

    async def test_document_kind_filter_passed_through(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        await search_red_hat_docs("test", ctx=ctx, document_kind="errata")

        call_kwargs = mock_client.aretrieve.call_args
        assert call_kwargs.kwargs.get("document_kind") == "errata"

    async def test_product_filter_passed_through(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        await search_red_hat_docs(
            "test", ctx=ctx, product="Red Hat Enterprise Linux"
        )

        call_kwargs = mock_client.aretrieve.call_args
        assert call_kwargs.kwargs.get("product") == "Red Hat Enterprise Linux"

    async def test_product_filter_resolved_from_partial_name(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        await search_red_hat_docs("test", ctx=ctx, product="Ansible")

        call_kwargs = mock_client.aretrieve.call_args
        assert call_kwargs.kwargs.get("product") == "Red Hat Ansible Automation Platform"

    async def test_product_filter_resolved_without_red_hat_prefix(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = EMPTY_RESULT
        ctx = _mock_ctx(client=mock_client)

        await search_red_hat_docs(
            "test", ctx=ctx, product="Ansible Automation Platform"
        )

        call_kwargs = mock_client.aretrieve.call_args
        assert call_kwargs.kwargs.get("product") == "Red Hat Ansible Automation Platform"


class TestResolveProduct:
    def test_exact_match(self) -> None:
        assert (
            _resolve_product("Red Hat Enterprise Linux", KNOWN_PRODUCTS)
            == "Red Hat Enterprise Linux"
        )

    def test_case_insensitive_exact_match(self) -> None:
        assert (
            _resolve_product("red hat enterprise linux", KNOWN_PRODUCTS)
            == "Red Hat Enterprise Linux"
        )

    def test_partial_name_single_match(self) -> None:
        assert (
            _resolve_product("Ansible", KNOWN_PRODUCTS)
            == "Red Hat Ansible Automation Platform"
        )

    def test_partial_name_without_prefix(self) -> None:
        assert (
            _resolve_product("Ansible Automation Platform", KNOWN_PRODUCTS)
            == "Red Hat Ansible Automation Platform"
        )

    def test_substring_match(self) -> None:
        assert (
            _resolve_product("Satellite", KNOWN_PRODUCTS)
            == "Red Hat Satellite"
        )

    def test_no_match_returns_original(self) -> None:
        assert _resolve_product("NonExistent Product", KNOWN_PRODUCTS) == "NonExistent Product"

    def test_empty_name_returns_empty(self) -> None:
        assert _resolve_product("", KNOWN_PRODUCTS) == ""

    def test_empty_products_returns_original(self) -> None:
        assert _resolve_product("Ansible", []) == "Ansible"

    def test_multiple_matches_picks_shortest(self) -> None:
        result = _resolve_product("OpenShift", KNOWN_PRODUCTS)
        assert result == "OpenShift Container Platform"


class TestCheckOkpHealth:
    async def test_healthy(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.return_value = FAKE_RESULT
        ctx = _mock_ctx(client=mock_client)

        result = await check_okp_health(ctx=ctx)

        parsed = json.loads(result)
        assert parsed["status"] == "healthy"
        assert "solr_handler" in parsed
        assert "products_available" in parsed

    async def test_unhealthy(self) -> None:
        mock_client = AsyncMock()
        mock_client.aretrieve.side_effect = OKPConnectionError("unreachable")
        ctx = _mock_ctx(client=mock_client)

        result = await check_okp_health(ctx=ctx)

        parsed = json.loads(result)
        assert parsed["status"] == "unhealthy"
        assert "unreachable" in parsed["error"]


class TestToolAnnotations:
    def test_search_tool_is_read_only(self) -> None:
        assert _SEARCH_ANNOTATIONS.readOnlyHint is True

    def test_search_tool_is_idempotent(self) -> None:
        assert _SEARCH_ANNOTATIONS.idempotentHint is True

    def test_search_tool_is_not_open_world(self) -> None:
        assert _SEARCH_ANNOTATIONS.openWorldHint is False

    def test_search_tool_is_not_destructive(self) -> None:
        assert _SEARCH_ANNOTATIONS.destructiveHint is False

    def test_health_tool_is_read_only(self) -> None:
        assert _HEALTH_ANNOTATIONS.readOnlyHint is True

    def test_health_tool_is_idempotent(self) -> None:
        assert _HEALTH_ANNOTATIONS.idempotentHint is True


class TestServerConfiguration:
    def test_server_has_lifespan(self) -> None:
        assert mcp._lifespan is not None

    def test_server_name(self) -> None:
        assert mcp.name == "OKP Search"
