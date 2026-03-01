"""Tests for rhokp.retrievers.OKPLangChainRetriever.

Requires: pip install rhokp[langchain,dev]
Mocks the OKPClient so no real OKP or network is needed.
"""

from __future__ import annotations

import pytest

from rhokp.models import OKPConnectionError, OKPDocument, RetrieveResult
from rhokp.retrievers import OKPLangChainRetriever


def _make_result(docs: list[OKPDocument] | None = None) -> RetrieveResult:
    docs = docs or []
    return RetrieveResult(
        query="test",
        num_found=len(docs),
        docs=docs,
        context="",
    )


def test_retriever_returns_documents_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = [
        OKPDocument(
            title="Installing OpenShift",
            snippet="Use the installer to deploy...",
            url_slug="installing-openshift",
            resource_name="doc-1",
            document_kind="documentation",
            product="OpenShift Container Platform",
            version="4.16",
            score=28.5,
        ),
        OKPDocument(
            title="Bare metal install",
            snippet="For bare metal, prepare the nodes...",
            url_slug="bare-metal",
            resource_name="doc-2",
            document_kind="guide",
        ),
    ]
    mock_result = _make_result(docs)

    from unittest.mock import patch, MagicMock

    with patch("rhokp.retrievers.OKPClient") as MockClient:
        instance = MagicMock()
        instance.retrieve.return_value = mock_result
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = instance

        retriever = OKPLangChainRetriever(base_url="http://okp:8080", rows=5)
        result = retriever.invoke("install OpenShift")

    assert len(result) == 2
    assert result[0].page_content.startswith("Installing OpenShift")
    assert "Use the installer" in result[0].page_content
    assert result[0].metadata["title"] == "Installing OpenShift"
    assert result[0].metadata["product"] == "OpenShift Container Platform"
    assert result[0].metadata["version"] == "4.16"
    assert result[0].metadata["score"] == 28.5


def test_retriever_returns_empty_list_on_okp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import patch, MagicMock

    with patch("rhokp.retrievers.OKPClient") as MockClient:
        instance = MagicMock()
        instance.retrieve.side_effect = OKPConnectionError("unreachable")
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = instance

        retriever = OKPLangChainRetriever(base_url="http://okp:8080")
        result = retriever.invoke("install OpenShift")

    assert result == []


def test_retriever_raises_on_error_when_configured() -> None:
    from unittest.mock import patch, MagicMock

    with patch("rhokp.retrievers.OKPClient") as MockClient:
        instance = MagicMock()
        instance.retrieve.side_effect = OKPConnectionError("unreachable")
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = instance

        retriever = OKPLangChainRetriever(base_url="http://okp:8080", raise_on_error=True)
        with pytest.raises(RuntimeError, match="unreachable"):
            retriever.invoke("install OpenShift")


def test_retriever_empty_query_returns_empty_list() -> None:
    retriever = OKPLangChainRetriever(base_url="http://okp:8080")
    assert retriever.invoke("") == []
    assert retriever.invoke("   ") == []


def test_retriever_metadata_includes_new_fields() -> None:
    docs = [
        OKPDocument(
            title="T",
            snippet="S",
            url_slug="slug",
            resource_name="rn",
            document_kind="dk",
            product="P",
            version="1.0",
            score=10.5,
            view_uri="/docs/t",
        )
    ]
    mock_result = _make_result(docs)

    from unittest.mock import patch, MagicMock

    with patch("rhokp.retrievers.OKPClient") as MockClient:
        instance = MagicMock()
        instance.retrieve.return_value = mock_result
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = instance

        retriever = OKPLangChainRetriever(base_url="http://okp:8080")
        result = retriever.invoke("x")

    assert len(result) == 1
    meta = result[0].metadata
    assert meta["product"] == "P"
    assert meta["version"] == "1.0"
    assert meta["score"] == 10.5
    assert meta["view_uri"] == "/docs/t"
