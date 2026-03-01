"""Tests for the CLI entry point (python -m rhokp)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from rhokp.__main__ import main
from rhokp.models import OKPConnectionError, OKPDocument, RetrieveResult


def test_main_success(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["rhokp", "test", "query"])
    fake_result = RetrieveResult(
        query="test query",
        num_found=1,
        docs=[
            OKPDocument(
                title="Test",
                snippet="Content.",
                url_slug="test",
                resource_name="r1",
                document_kind="guide",
                product="RHEL",
                score=10.0,
            )
        ],
        context="[1] Test (guide, RHEL)\nContent.\nSource: /test",
    )
    with patch("rhokp.__main__.retrieve", return_value=fake_result):
        main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["query"] == "test query"
    assert output["num_found"] == 1
    assert output["docs"][0]["product"] == "RHEL"


def test_main_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["rhokp"])
    with pytest.raises(SystemExit):
        main()


def test_main_okp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["rhokp", "test"])
    with patch("rhokp.__main__.retrieve", side_effect=OKPConnectionError("unreachable")):
        with pytest.raises(SystemExit, match="1"):
            main()


def test_main_context_only(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["rhokp", "--context-only", "test"])
    fake_result = RetrieveResult(
        query="test",
        num_found=1,
        docs=[
            OKPDocument(
                title="Test",
                snippet="Content.",
                url_slug="test",
                resource_name="r1",
                document_kind="guide",
            )
        ],
        context="[1] Test (guide)\nContent.\nSource: /test",
    )
    with patch("rhokp.__main__.retrieve", return_value=fake_result):
        main()

    captured = capsys.readouterr()
    assert "[1] Test" in captured.out
    assert "Source: /test" in captured.out
