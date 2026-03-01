"""
Data models and exception hierarchy for OKP retrieval.

All public types used by the rhokp library are defined here. Models are
frozen dataclasses to ensure immutability and safe use across threads.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_HIGHLIGHT_TAG_RE = re.compile(r"</?b>")

_SOLR_SPECIAL_CHARS = re.compile(r'([+\-&|!(){}[\]^"~*?:\\\/])')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OKPError(Exception):
    """Base exception for all OKP retrieval errors."""


class OKPConnectionError(OKPError):
    """OKP is unreachable or a transport-level error occurred (DNS, TCP, TLS, timeout)."""


class OKPSearchError(OKPError):
    """OKP returned an HTTP error (4xx/5xx)."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class OKPResponseError(OKPError):
    """OKP returned a response that could not be parsed (bad JSON, unexpected schema)."""

    def __init__(self, message: str, raw_body: str = "") -> None:
        self.raw_body = raw_body[:2000]
        super().__init__(message)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OKPDocument:
    """A single document returned by OKP search.

    Fields are mapped from OKP's Solr schema. All text fields have HTML
    highlight tags stripped and HTML entities decoded.
    """

    title: str
    snippet: str
    url_slug: str
    resource_name: str
    document_kind: str
    product: str = ""
    version: str = ""
    score: float = 0.0
    last_modified: str = ""
    view_uri: str = ""
    summary: str = ""
    headings: list[str] = field(default_factory=list)
    severity: str = ""
    advisory_type: str = ""
    synopsis: str = ""


@dataclass(frozen=True)
class FacetCounts:
    """Facet counts from a Solr response, useful for filtering and result distribution."""

    products: dict[str, int] = field(default_factory=dict)
    document_kinds: dict[str, int] = field(default_factory=dict)
    versions: dict[str, int] = field(default_factory=dict)
    content_subtypes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrieveResult:
    """Typed result from an OKP retrieval call."""

    query: str
    num_found: int
    docs: list[OKPDocument]
    context: str
    facets: FacetCounts = field(default_factory=FacetCounts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (e.g. for JSON output)."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Text processing helpers
# ---------------------------------------------------------------------------


def clean_highlight(text: str) -> str:
    """Strip Solr highlight tags (<b>, </b>) and decode HTML entities.

    OKP's Solr config uses hl.encoder=html and <b> tags for highlighting.
    This function removes the tags and decodes entities like &#x27; &quot; etc.
    """
    text = _HIGHLIGHT_TAG_RE.sub("", text)
    return html.unescape(text)


def sanitize_query(query: str) -> str:
    """Escape Solr special characters to prevent query injection.

    Solr's query parser interprets characters like +, -, !, (, ), etc.
    as operators. This escapes them so they are treated as literals.
    """
    return _SOLR_SPECIAL_CHARS.sub(r"\\\1", query)
