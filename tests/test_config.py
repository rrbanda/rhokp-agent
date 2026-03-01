"""Tests for rhokp.config -- configuration validation and env loading."""

from __future__ import annotations

import pytest

from rhokp.config import OKPConfig


class TestOKPConfigValidation:
    def test_defaults_are_valid(self) -> None:
        config = OKPConfig()
        assert config.base_url == "http://127.0.0.1:8080"
        assert config.rows == 5
        assert config.timeout_connect == 5.0
        assert config.timeout_read == 25.0
        assert config.retries == 2

    def test_rows_too_low(self) -> None:
        with pytest.raises(ValueError, match="rows must be 1-100"):
            OKPConfig(rows=0)

    def test_rows_too_high(self) -> None:
        with pytest.raises(ValueError, match="rows must be 1-100"):
            OKPConfig(rows=101)

    def test_empty_base_url(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            OKPConfig(base_url="")

    def test_negative_timeout(self) -> None:
        with pytest.raises(ValueError, match="timeout_connect"):
            OKPConfig(timeout_connect=-1)

    def test_negative_retries(self) -> None:
        with pytest.raises(ValueError, match="retries"):
            OKPConfig(retries=-1)

    def test_custom_values(self) -> None:
        config = OKPConfig(
            base_url="http://custom:9090",
            rows=10,
            timeout_connect=3.0,
            timeout_read=15.0,
            retries=5,
            verify_ssl=False,
        )
        assert config.base_url == "http://custom:9090"
        assert config.rows == 10
        assert config.verify_ssl is False

    def test_frozen(self) -> None:
        config = OKPConfig()
        with pytest.raises(AttributeError):
            config.rows = 10  # type: ignore[misc]

    def test_multiple_validation_errors(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            OKPConfig(rows=0, timeout_connect=-1)
        assert "rows" in str(exc_info.value)
        assert "timeout_connect" in str(exc_info.value)


class TestOKPConfigFromEnv:
    def test_reads_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_BASE_URL", "http://from-env:9999")
        config = OKPConfig.from_env()
        assert config.base_url == "http://from-env:9999"

    def test_strips_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_BASE_URL", "http://host:8080/")
        config = OKPConfig.from_env()
        assert config.base_url == "http://host:8080"

    def test_reads_rows_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_RAG_ROWS", "10")
        config = OKPConfig.from_env()
        assert config.rows == 10

    def test_invalid_rows_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_RAG_ROWS", "abc")
        with pytest.raises(ValueError, match="RHOKP_RAG_ROWS"):
            OKPConfig.from_env()

    def test_overrides_take_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_BASE_URL", "http://env-url:8080")
        config = OKPConfig.from_env(base_url="http://override:9090")
        assert config.base_url == "http://override:9090"

    def test_verify_ssl_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_VERIFY_SSL", "true")
        config = OKPConfig.from_env()
        assert config.verify_ssl is True

    def test_verify_ssl_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_VERIFY_SSL", "false")
        config = OKPConfig.from_env()
        assert config.verify_ssl is False

    def test_verify_ssl_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RHOKP_VERIFY_SSL", "/path/to/ca-bundle.crt")
        config = OKPConfig.from_env()
        assert config.verify_ssl == "/path/to/ca-bundle.crt"

    def test_none_overrides_ignored(self) -> None:
        config = OKPConfig.from_env(base_url=None, rows=None)
        assert config.base_url == "http://127.0.0.1:8080"
        assert config.rows == 5
