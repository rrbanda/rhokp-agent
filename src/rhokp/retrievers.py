"""
LangChain retriever adapter for OKP.

Requires the optional dependency: pip install rhokp[langchain]

Provides OKPLangChainRetriever, a LangChain BaseRetriever that calls the
OKP search API via rhokp.client and returns LangChain Documents.

Example:
    from rhokp.retrievers import OKPLangChainRetriever
    retriever = OKPLangChainRetriever(base_url="http://127.0.0.1:8080", rows=5)
    docs = retriever.invoke("How do I install OpenShift?")
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from rhokp.client import OKPClient, aretrieve as okp_aretrieve
from rhokp.config import OKPConfig
from rhokp.models import OKPDocument, OKPError

logger = logging.getLogger(__name__)


def _doc_to_langchain(doc: OKPDocument) -> Document:
    """Convert an OKPDocument to a LangChain Document with full metadata."""
    page_content = f"{doc.title}\n{doc.snippet}".strip() or "(No content)"
    metadata: dict[str, Any] = {
        "title": doc.title,
        "url_slug": doc.url_slug,
        "resource_name": doc.resource_name,
        "document_kind": doc.document_kind,
        "product": doc.product,
        "version": doc.version,
        "score": doc.score,
        "last_modified": doc.last_modified,
        "view_uri": doc.view_uri,
        "severity": doc.severity,
        "advisory_type": doc.advisory_type,
    }
    return Document(page_content=page_content, metadata=metadata)


class OKPLangChainRetriever(BaseRetriever):
    """LangChain retriever backed by the Red Hat Offline Knowledge Portal (OKP).

    Queries OKP via an OKPClient and returns LangChain Documents suitable
    for RAG chains. On OKP errors, returns an empty list by default (so
    chains degrade gracefully) unless raise_on_error is True.

    Supports filtering by product, version, and document kind via
    search_kwargs or constructor parameters.
    """

    base_url: Optional[str] = None
    rows: Optional[int] = None
    product: Optional[str] = None
    version: Optional[str] = None
    document_kind: Optional[str] = None
    raise_on_error: bool = False

    model_config = {"arbitrary_types_allowed": True}

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None,
    ) -> List[Document]:
        query = (query or "").strip()
        if not query:
            logger.warning("OKPLangChainRetriever: empty query, returning no documents")
            return []

        logger.debug(
            "OKPLangChainRetriever: query=%r product=%r version=%r kind=%r",
            query,
            self.product,
            self.version,
            self.document_kind,
        )
        t0 = time.monotonic()

        config_overrides: dict[str, Any] = {}
        if self.base_url is not None:
            config_overrides["base_url"] = self.base_url
        if self.rows is not None:
            config_overrides["rows"] = self.rows

        try:
            config = OKPConfig.from_env(**config_overrides)
            with OKPClient(config) as client:
                result = client.retrieve(
                    query,
                    rows=self.rows,
                    product=self.product,
                    version=self.version,
                    document_kind=self.document_kind,
                )
        except (OKPError, ValueError) as exc:
            elapsed = (time.monotonic() - t0) * 1000
            if self.raise_on_error:
                raise RuntimeError(str(exc)) from exc
            logger.warning("OKPLangChainRetriever: %s (%.1fms)", exc, elapsed)
            return []

        out: List[Document] = []
        for doc in result.docs:
            try:
                out.append(_doc_to_langchain(doc))
            except Exception as exc:
                logger.warning("OKPLangChainRetriever: skipped malformed doc: %s", exc)

        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            "OKPLangChainRetriever: query=%r num_found=%d returned=%d elapsed_ms=%.1f",
            query,
            result.num_found,
            len(out),
            elapsed,
        )
        return out

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[AsyncCallbackManagerForRetrieverRun] = None,
    ) -> List[Document]:
        """Native async retrieval using aretrieve() -- no thread pool needed."""
        query = (query or "").strip()
        if not query:
            return []

        logger.debug("OKPLangChainRetriever async: query=%r", query)
        t0 = time.monotonic()

        try:
            result = await okp_aretrieve(
                query,
                base_url=self.base_url,
                rows=self.rows,
                product=self.product,
                version=self.version,
                document_kind=self.document_kind,
            )
        except (OKPError, ValueError) as exc:
            elapsed = (time.monotonic() - t0) * 1000
            if self.raise_on_error:
                raise RuntimeError(str(exc)) from exc
            logger.warning("OKPLangChainRetriever async: %s (%.1fms)", exc, elapsed)
            return []

        out: List[Document] = []
        for doc in result.docs:
            try:
                out.append(_doc_to_langchain(doc))
            except Exception as exc:
                logger.warning("OKPLangChainRetriever: skipped malformed doc: %s", exc)

        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            "OKPLangChainRetriever async: query=%r num_found=%d returned=%d elapsed_ms=%.1f",
            query,
            result.num_found,
            len(out),
            elapsed,
        )
        return out


__all__ = ["OKPLangChainRetriever"]
