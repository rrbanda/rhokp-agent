"""
OKP client with persistent HTTP connections and production resilience.

Provides ``OKPClient`` for use in servers and pipelines (connection pooling,
validated config, context manager support) and module-level convenience
functions ``retrieve()`` / ``aretrieve()`` for one-shot use.

Usage:
    # One-shot (creates and closes a client per call):
    from rhokp import retrieve
    result = retrieve("install OpenShift")

    # Persistent client (recommended for servers and pipelines):
    from rhokp import OKPClient
    with OKPClient() as client:
        result = client.retrieve("install OpenShift")
        result2 = client.retrieve("configure networking", product="OpenShift Container Platform")
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import time
from contextlib import nullcontext
from typing import Any

import httpx

from rhokp.config import OKPConfig
from rhokp.models import (
    FacetCounts,
    OKPConnectionError,
    OKPDocument,
    OKPError,
    OKPResponseError,
    OKPSearchError,
    RetrieveResult,
    clean_highlight,
    sanitize_query,
)
from rhokp.preprocessing import expand_query

logger = logging.getLogger(__name__)

try:
    _PKG_VERSION = importlib.metadata.version("rhokp")
except importlib.metadata.PackageNotFoundError:
    _PKG_VERSION = "dev"

_USER_AGENT = f"rhokp-agent/{_PKG_VERSION}"

_otel_tracer: Any = None
try:
    from opentelemetry import trace

    _otel_tracer = trace.get_tracer("rhokp")
except ImportError:
    pass


_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def _backoff_delay(attempt: int, base: float, maximum: float) -> float:
    """Compute exponential backoff delay for the given attempt (0-indexed)."""
    return min(base * (2**attempt), maximum)


class _CircuitBreaker:
    """Three-state circuit breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int, reset_timeout: float) -> None:
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._enabled = failure_threshold > 0

    @property
    def state(self) -> str:
        return self._state

    def check(self) -> None:
        """Raise OKPConnectionError if circuit is open."""
        if not self._enabled:
            return
        if self._state == self.OPEN:
            if time.monotonic() - self._last_failure_time >= self._reset_timeout:
                self._state = self.HALF_OPEN
            else:
                raise OKPConnectionError(
                    "Circuit breaker is open: OKP has failed "
                    f"{self._failure_count} consecutive times"
                )

    def record_success(self) -> None:
        if not self._enabled:
            return
        prev = self._state
        self._failure_count = 0
        self._state = self.CLOSED
        if prev != self.CLOSED:
            logger.info(
                "Circuit breaker %s -> %s after successful request",
                prev,
                self.CLOSED,
            )

    def record_failure(self) -> None:
        if not self._enabled:
            return
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._threshold:
            prev = self._state
            self._state = self.OPEN
            if prev != self.OPEN:
                logger.warning(
                    "Circuit breaker %s -> %s after %d consecutive failures",
                    prev,
                    self.OPEN,
                    self._failure_count,
                )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000


def _otel_span(name: str, query: str, rows: int, base_url: str) -> Any:
    """Return an OTel span context manager, or nullcontext if OTel is absent."""
    if _otel_tracer is not None:
        return _otel_tracer.start_as_current_span(
            name,
            attributes={"okp.query": query, "okp.rows": rows, "okp.base_url": base_url},
        )
    return nullcontext()


def _build_solr_params(
    query: str,
    rows: int,
    *,
    product: str | None = None,
    version: str | None = None,
    document_kind: str | None = None,
    extra_fq: list[str] | None = None,
) -> dict[str, Any]:
    """Build Solr query parameters.

    Only sends ``q``, ``rows``, ``wt``, and filter queries (``fq``).
    All other parameters (edismax, boosting, highlighting, faceting) are
    already configured as tuned defaults in OKP's solrconfig.xml.
    """
    params: dict[str, Any] = {
        "q": query,
        "rows": rows,
        "wt": "json",
    }

    fq: list[str] = []
    if product:
        fq.append(f'product:"{product}"')
    if version:
        fq.append(f'documentation_version:"{version}"')
    if document_kind:
        fq.append(f'documentKind:"{document_kind}"')
    if extra_fq:
        fq.extend(extra_fq)
    if fq:
        params["fq"] = fq

    return params


def _parse_facets(data: dict[str, Any]) -> FacetCounts:
    """Parse Solr facet_counts into a FacetCounts object."""
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
    """Parse a Solr JSON response into typed OKPDocument list and facets.

    Validates the response structure defensively and raises OKPResponseError
    on unexpected shapes rather than letting TypeErrors propagate.
    """
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


def _build_context(docs: list[OKPDocument], max_chars: int = 0) -> str:
    """Build a numbered context string for LLM prompts with source citations.

    Formats security content (CVEs, errata) differently from documentation,
    including severity and advisory type when available.

    When *max_chars* > 0 the output is truncated at the character budget,
    dropping later entries rather than cutting mid-entry.
    """
    parts: list[str] = []
    for i, doc in enumerate(docs, 1):
        header = f"[{i}] {doc.title}"
        meta_parts: list[str] = []
        if doc.document_kind:
            meta_parts.append(doc.document_kind)
        if doc.product:
            meta_parts.append(doc.product)
        if doc.version:
            meta_parts.append(f"v{doc.version}")
        if meta_parts:
            header += f" ({', '.join(meta_parts)})"
        if doc.severity:
            header += f" [{doc.severity}]"

        body = doc.synopsis or doc.snippet
        if doc.advisory_type and doc.synopsis and doc.snippet and doc.snippet != doc.synopsis:
            body = f"{doc.synopsis}\n{doc.snippet}"

        entry = f"{header}\n{body}"
        if doc.url_slug:
            entry += f"\nSource: /{doc.url_slug}"
        parts.append(entry)

    if max_chars > 0:
        result_parts: list[str] = []
        current_len = 0
        for part in parts:
            entry_len = len(part) + 2  # +2 for "\n\n" separator
            if current_len + entry_len > max_chars and result_parts:
                break
            result_parts.append(part)
            current_len += entry_len
        return "\n\n".join(result_parts)

    return "\n\n".join(parts)


def _validate_query(query: str, max_length: int) -> str:
    """Validate and normalize query input. Returns stripped query."""
    query = (query or "").strip()
    if not query:
        raise ValueError("query must be a non-empty string")
    if len(query) > max_length:
        raise ValueError(f"query length {len(query)} exceeds maximum {max_length}")
    return query


def _handle_http_error(
    exc: Exception,
    query: str,
    t0: float,
    base_url: str,
) -> None:
    """Map httpx exceptions to OKP exceptions. Always raises."""
    elapsed = _elapsed_ms(t0)
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text[:500] if exc.response else ""
        logger.warning(
            "OKP HTTP %d for query=%r (%.1fms)",
            exc.response.status_code,
            query,
            elapsed,
        )
        raise OKPSearchError(exc.response.status_code, detail) from exc

    if isinstance(exc, httpx.ConnectError):
        logger.warning("OKP connection failed for query=%r (%.1fms): %s", query, elapsed, exc)
        raise OKPConnectionError(f"Cannot connect to OKP at {base_url}: {exc}") from exc

    if isinstance(exc, httpx.TimeoutException):
        logger.warning("OKP timeout for query=%r (%.1fms)", query, elapsed)
        raise OKPConnectionError(f"Timeout connecting to OKP at {base_url}: {exc}") from exc

    if isinstance(exc, httpx.DecodingError):
        logger.warning("OKP decoding error for query=%r (%.1fms): %s", query, elapsed, exc)
        raise OKPResponseError(f"Failed to decode OKP response: {exc}") from exc

    logger.warning("OKP error for query=%r (%.1fms): %s", query, elapsed, exc)
    raise OKPConnectionError(f"OKP request failed: {exc}") from exc


def _finalize(
    query: str,
    data: dict[str, Any],
    t0: float,
    max_context_chars: int = 0,
) -> RetrieveResult:
    """Parse response, log, set OTel attributes, and return result."""
    elapsed = _elapsed_ms(t0)
    docs, num_found, facets = _parse_response(data)

    logger.info(
        "OKP query=%r num_found=%d returned=%d elapsed_ms=%.1f",
        query,
        num_found,
        len(docs),
        elapsed,
    )

    if _otel_tracer is not None:
        try:
            from opentelemetry import trace as _trace

            span = _trace.get_current_span()
            span.set_attribute("okp.num_found", num_found)
            span.set_attribute("okp.docs_returned", len(docs))
            span.set_attribute("okp.elapsed_ms", elapsed)
        except Exception:
            pass

    return RetrieveResult(
        query=query,
        num_found=num_found,
        docs=docs,
        context=_build_context(docs, max_chars=max_context_chars),
        facets=facets,
    )


# ---------------------------------------------------------------------------
# OKPClient
# ---------------------------------------------------------------------------


class OKPClient:
    """Persistent OKP client with connection pooling and context manager support.

    Recommended for servers and pipelines where multiple queries are made.
    Holds a persistent httpx.Client with connection pooling.

    Usage:
        with OKPClient() as client:
            result = client.retrieve("install OpenShift")
    """

    def __init__(
        self,
        config: OKPConfig | None = None,
        *,
        backend: Any | None = None,
        _sync_transport: httpx.BaseTransport | None = None,
        _async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config or OKPConfig.from_env()
        self._url = f"{self._config.base_url}{self._config.solr_handler}"
        self._backend = backend

        timeout = httpx.Timeout(
            connect=self._config.timeout_connect,
            read=self._config.timeout_read,
            pool=self._config.timeout_pool,
            write=self._config.timeout_read,
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }

        transport = _sync_transport or httpx.HTTPTransport(
            retries=self._config.retries,
            verify=self._config.verify_ssl,  # type: ignore[arg-type]
        )
        self._sync_client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers=headers,
        )

        async_transport = _async_transport or httpx.AsyncHTTPTransport(
            retries=self._config.retries,
            verify=self._config.verify_ssl,  # type: ignore[arg-type]
        )
        self._async_client = httpx.AsyncClient(
            transport=async_transport,
            timeout=timeout,
            headers=headers,
        )

        self._closed = False
        self._breaker = _CircuitBreaker(
            self._config.circuit_failure_threshold,
            self._config.circuit_reset_timeout,
        )
        self._cache: dict[str, tuple[RetrieveResult, float]] = {}

        logger.debug(
            "OKPClient created url=%s rows=%d timeout_read=%.1f retries=%d",
            self._url,
            self._config.rows,
            self._config.timeout_read,
            self._config.retries,
        )

    @property
    def config(self) -> OKPConfig:
        return self._config

    @staticmethod
    def _cache_key(
        query: str,
        rows: int,
        product: str | None,
        version: str | None,
        document_kind: str | None,
    ) -> str:
        return f"{query}\x00{rows}\x00{product}\x00{version}\x00{document_kind}"

    def _cache_get(self, key: str) -> RetrieveResult | None:
        if self._config.cache_ttl <= 0:
            return None
        cached = self._cache.get(key)
        if cached and (time.monotonic() - cached[1]) < self._config.cache_ttl:
            logger.debug("OKP cache hit for key=%r", key)
            return cached[0]
        if cached:
            del self._cache[key]
        return None

    def _cache_put(self, key: str, result: RetrieveResult) -> None:
        if self._config.cache_ttl <= 0:
            return
        if len(self._cache) >= self._config.cache_max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
        self._cache[key] = (result, time.monotonic())

    def clear_cache(self) -> None:
        """Remove all cached responses."""
        self._cache.clear()

    def retrieve(
        self,
        query: str,
        *,
        rows: int | None = None,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
        sanitize: bool = True,
    ) -> RetrieveResult:
        """Retrieve relevant docs from OKP for RAG context.

        Args:
            query: Search query string (must be non-empty).
            rows: Override default rows for this call.
            product: Filter by product name (e.g. "OpenShift Container Platform").
            version: Filter by documentation version (e.g. "4.16").
            document_kind: Filter by kind (e.g. "documentation", "solution").
            sanitize: Escape Solr special characters in query (default True).

        Returns:
            RetrieveResult with query, num_found, docs, context, and facets.
        """
        if self._closed:
            raise RuntimeError("OKPClient is closed")

        effective_rows = rows if rows is not None else self._config.rows
        query = _validate_query(query, self._config.max_query_length)

        logger.debug(
            "OKP retrieve start query=%r rows=%d product=%r version=%r kind=%r",
            query,
            effective_rows,
            product,
            version,
            document_kind,
        )

        cache_k = self._cache_key(query, effective_rows, product, version, document_kind)
        cached = self._cache_get(cache_k)
        if cached is not None:
            return cached

        effective_query = expand_query(query) if self._config.expand_synonyms else query
        solr_query = sanitize_query(effective_query) if sanitize else effective_query
        params = _build_solr_params(
            solr_query,
            effective_rows,
            product=product,
            version=version,
            document_kind=document_kind,
        )

        max_attempts = 1 + self._config.retry_max_attempts

        with _otel_span("okp.retrieve", query, effective_rows, self._config.base_url):
            t0 = time.monotonic()
            last_exc: Exception | None = None

            for attempt in range(max_attempts):
                if attempt > 0:
                    delay = _backoff_delay(
                        attempt - 1,
                        self._config.retry_backoff_base,
                        self._config.retry_backoff_max,
                    )
                    logger.info(
                        "OKP retry %d/%d after %.1fs for query=%r",
                        attempt,
                        self._config.retry_max_attempts,
                        delay,
                        query,
                    )
                    time.sleep(delay)

                self._breaker.check()
                try:
                    if self._backend is not None:
                        docs, num_found, facets = self._backend.search(
                            solr_query,
                            effective_rows,
                            product=product,
                            version=version,
                            document_kind=document_kind,
                        )
                        self._breaker.record_success()
                        result = RetrieveResult(
                            query=query,
                            num_found=num_found,
                            docs=docs,
                            context=_build_context(docs, max_chars=self._config.max_context_chars),
                            facets=facets,
                        )
                    else:
                        resp = self._sync_client.get(self._url, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                        self._breaker.record_success()
                        result = _finalize(query, data, t0, self._config.max_context_chars)
                    self._cache_put(cache_k, result)
                    return result
                except httpx.HTTPStatusError as exc:
                    self._breaker.record_failure()
                    if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                        _handle_http_error(exc, query, t0, self._config.base_url)
                    last_exc = exc
                except httpx.HTTPError as exc:
                    self._breaker.record_failure()
                    last_exc = exc
                except OKPError as exc:
                    self._breaker.record_failure()
                    last_exc = exc

            assert last_exc is not None
            if isinstance(last_exc, OKPError):
                raise last_exc
            _handle_http_error(last_exc, query, t0, self._config.base_url)
            raise last_exc  # unreachable, but satisfies type checker

    async def aretrieve(
        self,
        query: str,
        *,
        rows: int | None = None,
        product: str | None = None,
        version: str | None = None,
        document_kind: str | None = None,
        sanitize: bool = True,
    ) -> RetrieveResult:
        """Async variant of retrieve(). Uses the persistent async client."""
        if self._closed:
            raise RuntimeError("OKPClient is closed")

        effective_rows = rows if rows is not None else self._config.rows
        query = _validate_query(query, self._config.max_query_length)

        logger.debug(
            "OKP aretrieve start query=%r rows=%d product=%r version=%r kind=%r",
            query,
            effective_rows,
            product,
            version,
            document_kind,
        )

        cache_k = self._cache_key(query, effective_rows, product, version, document_kind)
        cached = self._cache_get(cache_k)
        if cached is not None:
            return cached

        effective_query = expand_query(query) if self._config.expand_synonyms else query
        solr_query = sanitize_query(effective_query) if sanitize else effective_query
        params = _build_solr_params(
            solr_query,
            effective_rows,
            product=product,
            version=version,
            document_kind=document_kind,
        )

        max_attempts = 1 + self._config.retry_max_attempts

        with _otel_span("okp.aretrieve", query, effective_rows, self._config.base_url):
            t0 = time.monotonic()
            last_exc: Exception | None = None

            for attempt in range(max_attempts):
                if attempt > 0:
                    delay = _backoff_delay(
                        attempt - 1,
                        self._config.retry_backoff_base,
                        self._config.retry_backoff_max,
                    )
                    logger.info(
                        "OKP retry %d/%d after %.1fs for query=%r",
                        attempt,
                        self._config.retry_max_attempts,
                        delay,
                        query,
                    )
                    await asyncio.sleep(delay)

                self._breaker.check()
                try:
                    if self._backend is not None:
                        docs, num_found, facets = await self._backend.asearch(
                            solr_query,
                            effective_rows,
                            product=product,
                            version=version,
                            document_kind=document_kind,
                        )
                        self._breaker.record_success()
                        result = RetrieveResult(
                            query=query,
                            num_found=num_found,
                            docs=docs,
                            context=_build_context(docs, max_chars=self._config.max_context_chars),
                            facets=facets,
                        )
                    else:
                        resp = await self._async_client.get(self._url, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                        self._breaker.record_success()
                        result = _finalize(query, data, t0, self._config.max_context_chars)
                    self._cache_put(cache_k, result)
                    return result
                except httpx.HTTPStatusError as exc:
                    self._breaker.record_failure()
                    if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                        _handle_http_error(exc, query, t0, self._config.base_url)
                    last_exc = exc
                except httpx.HTTPError as exc:
                    self._breaker.record_failure()
                    last_exc = exc
                except OKPError as exc:
                    self._breaker.record_failure()
                    last_exc = exc

            assert last_exc is not None
            if isinstance(last_exc, OKPError):
                raise last_exc
            _handle_http_error(last_exc, query, t0, self._config.base_url)
            raise last_exc  # unreachable

    def check_health(self) -> dict[str, object]:
        """Check OKP reachability and report basic status.

        Returns a dict with at minimum ``status`` ("healthy" or "unhealthy").
        On success, also includes ``num_indexed`` (total docs in the index),
        ``solr_handler``, and ``products_available`` (count of distinct products).

        This can be used to verify that OKP is running and accessible before
        making search queries. If RHOKP is running without an ACCESS_KEY,
        the number of indexed documents may be significantly lower than
        expected, indicating degraded (non-protected) content only.
        """
        try:
            result = self.retrieve("test", rows=1, sanitize=False)
            info: dict[str, object] = {
                "status": "healthy",
                "num_indexed": result.num_found,
                "solr_handler": self._config.solr_handler,
                "base_url": self._config.base_url,
            }
            if result.facets.products:
                info["products_available"] = len(result.facets.products)
            return info
        except OKPError as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
                "base_url": self._config.base_url,
            }

    def close(self) -> None:
        """Close the underlying HTTP clients."""
        if not self._closed:
            self._sync_client.close()
            self._closed = True
            logger.debug("OKPClient closed url=%s", self._url)

    async def aclose(self) -> None:
        """Close the underlying async HTTP client."""
        if not self._closed:
            await self._async_client.aclose()
            self._sync_client.close()
            self._closed = True
            logger.debug("OKPClient closed (async) url=%s", self._url)

    def __enter__(self) -> OKPClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    async def __aenter__(self) -> OKPClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def retrieve(
    query: str,
    *,
    base_url: str | None = None,
    rows: int | None = None,
    product: str | None = None,
    version: str | None = None,
    document_kind: str | None = None,
    timeout: float | None = None,
    retries: int | None = None,
    sanitize: bool = True,
    _transport_override: httpx.BaseTransport | None = None,
) -> RetrieveResult:
    """Retrieve relevant docs from OKP for RAG context (one-shot convenience).

    Creates a temporary client for a single call. For repeated use, prefer
    ``OKPClient`` which maintains a persistent connection pool.

    Args:
        query: Search query string (must be non-empty).
        base_url: OKP base URL. Falls back to RHOKP_BASE_URL env var.
        rows: Max documents to return. Falls back to RHOKP_RAG_ROWS env var.
        product: Filter by product name.
        version: Filter by documentation version.
        document_kind: Filter by document kind.
        timeout: HTTP read timeout in seconds (default 25.0).
        retries: Transport-level retries (default 2).
        sanitize: Escape Solr special characters (default True).

    Returns:
        RetrieveResult with query, num_found, docs, context, and facets.

    Raises:
        ValueError: If query is empty or too long, or rows out of range.
        OKPConnectionError: If OKP is unreachable or times out.
        OKPSearchError: If OKP returns an HTTP error (4xx/5xx).
        OKPResponseError: If OKP returns unparseable data.
    """
    overrides: dict[str, object] = {}
    if base_url is not None:
        overrides["base_url"] = base_url
    if rows is not None:
        overrides["rows"] = rows
    if timeout is not None:
        overrides["timeout_read"] = timeout
    if retries is not None:
        overrides["retries"] = retries

    config = OKPConfig.from_env(**overrides)
    with OKPClient(config, _sync_transport=_transport_override) as client:
        return client.retrieve(
            query,
            rows=rows,
            product=product,
            version=version,
            document_kind=document_kind,
            sanitize=sanitize,
        )


async def aretrieve(
    query: str,
    *,
    base_url: str | None = None,
    rows: int | None = None,
    product: str | None = None,
    version: str | None = None,
    document_kind: str | None = None,
    timeout: float | None = None,
    retries: int | None = None,
    sanitize: bool = True,
    _transport_override: httpx.AsyncBaseTransport | None = None,
) -> RetrieveResult:
    """Async variant of retrieve() (one-shot convenience).

    Same semantics as retrieve() but uses httpx.AsyncClient so it does not
    block the event loop. For repeated use, prefer ``OKPClient.aretrieve()``.
    """
    overrides: dict[str, object] = {}
    if base_url is not None:
        overrides["base_url"] = base_url
    if rows is not None:
        overrides["rows"] = rows
    if timeout is not None:
        overrides["timeout_read"] = timeout
    if retries is not None:
        overrides["retries"] = retries

    config = OKPConfig.from_env(**overrides)
    async with OKPClient(config, _async_transport=_transport_override) as client:
        return await client.aretrieve(
            query,
            rows=rows,
            product=product,
            version=version,
            document_kind=document_kind,
            sanitize=sanitize,
        )
