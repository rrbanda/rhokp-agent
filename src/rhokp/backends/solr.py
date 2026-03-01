"""Solr search backend for RHOKP.

Extracts the HTTP + parsing logic from ``client.py`` into a standalone class
that satisfies the :class:`~rhokp.backends.SearchBackend` protocol.
"""

from __future__ import annotations

import importlib.metadata
import logging
import time
from typing import Any

import httpx

from rhokp.config import OKPConfig
from rhokp.models import (
    FacetCounts,
    OKPConnectionError,
    OKPDocument,
    OKPResponseError,
    OKPSearchError,
    clean_highlight,
)

logger = logging.getLogger(__name__)

try:
    _PKG_VERSION = importlib.metadata.version("rhokp")
except importlib.metadata.PackageNotFoundError:
    _PKG_VERSION = "dev"

_USER_AGENT = f"rhokp-agent/{_PKG_VERSION}"


def _build_solr_params(
    query: str,
    rows: int,
    *,
    product: str | None = None,
    version: str | None = None,
    document_kind: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query, "rows": rows, "wt": "json"}
    fq: list[str] = []
    if product:
        fq.append(f'product:"{product}"')
    if version:
        fq.append(f'documentation_version:"{version}"')
    if document_kind:
        fq.append(f'documentKind:"{document_kind}"')
    if fq:
        params["fq"] = fq
    return params


class SolrBackend:
    """Default backend that queries RHOKP's embedded Solr instance.

    Holds its own ``httpx.Client`` / ``httpx.AsyncClient`` pair with connection
    pooling.  The class is usable as both sync and async context manager.
    """

    def __init__(
        self,
        config: OKPConfig,
        *,
        _sync_transport: httpx.BaseTransport | None = None,
        _async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._url = f"{config.base_url}{config.solr_handler}"

        timeout = httpx.Timeout(
            connect=config.timeout_connect,
            read=config.timeout_read,
            pool=config.timeout_pool,
            write=config.timeout_read,
        )
        headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}

        transport = _sync_transport or httpx.HTTPTransport(
            retries=config.retries,
            verify=config.verify_ssl,  # type: ignore[arg-type]
        )
        self._sync_client = httpx.Client(transport=transport, timeout=timeout, headers=headers)

        async_transport = _async_transport or httpx.AsyncHTTPTransport(
            retries=config.retries,
            verify=config.verify_ssl,  # type: ignore[arg-type]
        )
        self._async_client = httpx.AsyncClient(
            transport=async_transport, timeout=timeout, headers=headers
        )

    # -- Protocol methods ----------------------------------------------------

    def search(
        self,
        query: str,
        rows: int,
        *,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[OKPDocument], int, FacetCounts]:
        params = _build_solr_params(
            query, rows, product=product, version=version, document_kind=document_kind
        )
        t0 = time.monotonic()
        try:
            resp = self._sync_client.get(self._url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "SolrBackend HTTP %d query=%r elapsed_ms=%.1f",
                exc.response.status_code,
                query,
                elapsed,
            )
            detail = exc.response.text[:500] if exc.response else ""
            raise OKPSearchError(exc.response.status_code, detail) from exc
        except httpx.ConnectError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("SolrBackend connect failed query=%r elapsed_ms=%.1f", query, elapsed)
            raise OKPConnectionError(
                f"Cannot connect to OKP at {self._config.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("SolrBackend timeout query=%r elapsed_ms=%.1f", query, elapsed)
            raise OKPConnectionError(
                f"Timeout connecting to OKP at {self._config.base_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("SolrBackend error query=%r elapsed_ms=%.1f: %s", query, elapsed, exc)
            raise OKPConnectionError(f"OKP request failed: {exc}") from exc

        docs, num_found, facets = _parse_response(data)
        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            "SolrBackend query=%r num_found=%d returned=%d elapsed_ms=%.1f",
            query,
            num_found,
            len(docs),
            elapsed,
        )
        return docs, num_found, facets

    async def asearch(
        self,
        query: str,
        rows: int,
        *,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[OKPDocument], int, FacetCounts]:
        params = _build_solr_params(
            query, rows, product=product, version=version, document_kind=document_kind
        )
        t0 = time.monotonic()
        try:
            resp = await self._async_client.get(self._url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "SolrBackend async HTTP %d query=%r elapsed_ms=%.1f",
                exc.response.status_code,
                query,
                elapsed,
            )
            detail = exc.response.text[:500] if exc.response else ""
            raise OKPSearchError(exc.response.status_code, detail) from exc
        except httpx.ConnectError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "SolrBackend async connect failed query=%r elapsed_ms=%.1f", query, elapsed
            )
            raise OKPConnectionError(
                f"Cannot connect to OKP at {self._config.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("SolrBackend async timeout query=%r elapsed_ms=%.1f", query, elapsed)
            raise OKPConnectionError(
                f"Timeout connecting to OKP at {self._config.base_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "SolrBackend async error query=%r elapsed_ms=%.1f: %s", query, elapsed, exc
            )
            raise OKPConnectionError(f"OKP request failed: {exc}") from exc

        docs, num_found, facets = _parse_response(data)
        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            "SolrBackend async query=%r num_found=%d returned=%d elapsed_ms=%.1f",
            query,
            num_found,
            len(docs),
            elapsed,
        )
        return docs, num_found, facets

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._sync_client.close()

    async def aclose(self) -> None:
        await self._async_client.aclose()
        self._sync_client.close()

    def __enter__(self) -> SolrBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    async def __aenter__(self) -> SolrBackend:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


# ---------------------------------------------------------------------------
# Parsing helpers (shared with client.py — duplicated here intentionally
# so that solr.py is self-contained and can be imported independently)
# ---------------------------------------------------------------------------


def _parse_facets(data: dict[str, Any]) -> FacetCounts:
    facet_counts = data.get("facet_counts", {})
    facet_fields = facet_counts.get("facet_fields", {})

    def _pairs(raw: list[Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for i in range(0, len(raw) - 1, 2):
            name, count = raw[i], raw[i + 1]
            if isinstance(name, str) and isinstance(count, int) and count > 0:
                result[name] = count
        return result

    return FacetCounts(
        products=_pairs(facet_fields.get("product", [])),
        document_kinds=_pairs(facet_fields.get("documentKind", [])),
        versions=_pairs(facet_fields.get("documentation_version", [])),
        content_subtypes=_pairs(facet_fields.get("portal_content_subtype", [])),
    )


def _parse_response(data: dict[str, Any]) -> tuple[list[OKPDocument], int, FacetCounts]:
    response = data.get("response")
    if not isinstance(response, dict):
        raise OKPResponseError(
            f"Expected 'response' dict in Solr JSON, got {type(response).__name__}",
            raw_body=str(data)[:2000],
        )

    num_found = response.get("numFound", 0)
    if not isinstance(num_found, int):
        num_found = 0

    raw_docs = response.get("docs", [])
    if not isinstance(raw_docs, list):
        raw_docs = []

    highlighting = data.get("highlighting", {})
    if not isinstance(highlighting, dict):
        highlighting = {}

    docs: list[OKPDocument] = []
    for d in raw_docs:
        if not isinstance(d, dict):
            logger.warning("Skipping non-dict document in Solr response")
            continue

        resource = d.get("resourceName", "") or ""
        doc_id = d.get("id", resource) or resource

        hl = highlighting.get(doc_id, {})
        if not isinstance(hl, dict):
            hl = {}

        snippet_candidates = (
            (hl.get("main_content") or [])[:2]
            or (hl.get("title") or [])
            or [d.get("main_content", "") or ""]
        )
        raw_snippet = " ".join(s[:500] for s in snippet_candidates if isinstance(s, str))

        headings = d.get("heading_h2", [])
        if not isinstance(headings, list):
            headings = []

        severity = str(d.get("portal_severity", "")) or str(d.get("cve_threatSeverity", ""))

        docs.append(
            OKPDocument(
                title=clean_highlight(str(d.get("title", ""))),
                snippet=clean_highlight(raw_snippet),
                url_slug=str(d.get("url_slug", "")),
                resource_name=resource,
                document_kind=str(d.get("documentKind", "")),
                product=str(d.get("product", "")),
                version=str(d.get("documentation_version", "")),
                score=float(d.get("score", 0.0)),
                last_modified=str(d.get("lastModifiedDate", "")),
                view_uri=str(d.get("view_uri", "")),
                summary=clean_highlight(str(d.get("portal_summary", ""))),
                headings=[str(h) for h in headings if isinstance(h, str)],
                severity=severity,
                advisory_type=str(d.get("portal_advisory_type", "")),
                synopsis=clean_highlight(str(d.get("portal_synopsis", ""))),
            )
        )

    facets = _parse_facets(data)
    return docs, num_found, facets
