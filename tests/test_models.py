"""Tests for rhokp.models -- data models, text processing, and exceptions."""

from __future__ import annotations

import pytest

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


class TestCleanHighlight:
    def test_strips_b_tags(self) -> None:
        assert clean_highlight("foo <b>bar</b> baz") == "foo bar baz"

    def test_strips_nested_tags(self) -> None:
        assert clean_highlight("<b>text</b>") == "text"

    def test_decodes_html_entities(self) -> None:
        assert clean_highlight("it&#x27;s a &quot;test&quot;") == 'it\'s a "test"'

    def test_decodes_ampersand(self) -> None:
        assert clean_highlight("A &amp; B") == "A & B"

    def test_strips_tags_and_decodes_combined(self) -> None:
        assert clean_highlight("<b>Red Hat&#x27;s</b> product") == "Red Hat's product"

    def test_no_tags_unchanged(self) -> None:
        assert clean_highlight("plain text") == "plain text"

    def test_empty_string(self) -> None:
        assert clean_highlight("") == ""

    def test_preserves_angle_brackets_in_text(self) -> None:
        assert clean_highlight("use &lt;namespace&gt;") == "use <namespace>"

    def test_slash_in_entity(self) -> None:
        assert clean_highlight("path&#x2F;to&#x2F;file") == "path/to/file"


class TestSanitizeQuery:
    def test_escapes_parentheses(self) -> None:
        assert sanitize_query("install (openshift)") == "install \\(openshift\\)"

    def test_escapes_plus_minus(self) -> None:
        assert sanitize_query("+required -excluded") == "\\+required \\-excluded"

    def test_escapes_quotes(self) -> None:
        assert sanitize_query('"exact phrase"') == '\\"exact phrase\\"'

    def test_escapes_colon(self) -> None:
        assert sanitize_query("field:value") == "field\\:value"

    def test_escapes_asterisk_question(self) -> None:
        assert sanitize_query("wild* car?") == "wild\\* car\\?"

    def test_escapes_brackets(self) -> None:
        assert sanitize_query("[1 TO 10]") == "\\[1 TO 10\\]"

    def test_plain_text_unchanged(self) -> None:
        assert sanitize_query("install OpenShift") == "install OpenShift"

    def test_empty_string(self) -> None:
        assert sanitize_query("") == ""

    def test_escapes_backslash(self) -> None:
        assert sanitize_query("path\\to") == "path\\\\to"


class TestOKPDocument:
    def test_frozen_dataclass(self) -> None:
        doc = OKPDocument(
            title="Test",
            snippet="Content",
            url_slug="test-slug",
            resource_name="r1",
            document_kind="guide",
        )
        with pytest.raises(AttributeError):
            doc.title = "Modified"  # type: ignore[misc]

    def test_default_fields(self) -> None:
        doc = OKPDocument(
            title="T",
            snippet="S",
            url_slug="u",
            resource_name="r",
            document_kind="d",
        )
        assert doc.product == ""
        assert doc.version == ""
        assert doc.score == 0.0
        assert doc.headings == []

    def test_all_fields(self) -> None:
        doc = OKPDocument(
            title="Install Guide",
            snippet="How to install",
            url_slug="install",
            resource_name="r1",
            document_kind="documentation",
            product="OpenShift Container Platform",
            version="4.16",
            score=28.5,
            last_modified="2024-12-01",
            view_uri="/docs/install",
            summary="Installation guide",
            headings=["prerequisites", "steps"],
        )
        assert doc.product == "OpenShift Container Platform"
        assert doc.version == "4.16"
        assert doc.score == 28.5
        assert len(doc.headings) == 2


class TestRetrieveResult:
    def test_to_dict(self) -> None:
        result = RetrieveResult(
            query="test",
            num_found=1,
            docs=[
                OKPDocument(
                    title="T",
                    snippet="S",
                    url_slug="u",
                    resource_name="r",
                    document_kind="d",
                )
            ],
            context="[1] T\nS",
            facets=FacetCounts(products={"OpenShift": 10}),
        )
        d = result.to_dict()
        assert d["query"] == "test"
        assert d["num_found"] == 1
        assert len(d["docs"]) == 1
        assert d["facets"]["products"] == {"OpenShift": 10}


class TestExceptionHierarchy:
    def test_okp_error_is_base(self) -> None:
        assert issubclass(OKPConnectionError, OKPError)
        assert issubclass(OKPSearchError, OKPError)
        assert issubclass(OKPResponseError, OKPError)

    def test_search_error_has_status_code(self) -> None:
        err = OKPSearchError(503, "Service Unavailable")
        assert err.status_code == 503
        assert err.detail == "Service Unavailable"
        assert "503" in str(err)

    def test_response_error_truncates_body(self) -> None:
        err = OKPResponseError("bad json", raw_body="x" * 3000)
        assert len(err.raw_body) == 2000
