"""
Configuration for OKP retrieval.

All configuration is validated at construction time, not per-call.
Environment variables are read once via ``OKPConfig.from_env()`` and
the resulting object is immutable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8080"
_DEFAULT_SOLR_HANDLER = "/solr/portal/select"
_DEFAULT_ROWS = 5
_DEFAULT_TIMEOUT_CONNECT = 5.0
_DEFAULT_TIMEOUT_READ = 25.0
_DEFAULT_TIMEOUT_POOL = 10.0
_DEFAULT_RETRIES = 2
_MAX_ROWS = 100
_MAX_QUERY_LENGTH = 10_000


@dataclass(frozen=True)
class OKPConfig:
    """Validated, immutable configuration for OKP retrieval.

    Args:
        base_url: OKP base URL (no trailing slash).
        solr_handler: Solr request handler path. Use ``/solr/portal/select``
            (default) for general search or ``/solr/portal/select-errata``
            for errata-specific field boosting.
        rows: Default number of documents to return (1-100).
        timeout_connect: TCP connect timeout in seconds.
        timeout_read: HTTP read timeout in seconds.
        timeout_pool: Connection pool acquisition timeout in seconds.
        retries: Transport-level retries on connection failure.
        verify_ssl: TLS verification (True, False, or path to CA bundle).
        max_query_length: Maximum allowed query string length.
        max_context_chars: Max chars in the context string (0 = unlimited).
            Set to ``model_max_tokens * 4`` as a conservative estimate.
        circuit_failure_threshold: Consecutive failures before the circuit
            breaker opens (0 = disabled).
        circuit_reset_timeout: Seconds before an open circuit transitions
            to half-open.
        retry_max_attempts: App-level retries for retryable HTTP errors
            (429/502/503/504). 0 = disabled.
        retry_backoff_base: Initial backoff in seconds for exponential delay.
        retry_backoff_max: Maximum backoff in seconds.
        cache_ttl: TTL in seconds for response cache entries (0 = disabled).
        cache_max_entries: Max cached results before eviction.
        expand_synonyms: Expand Red Hat abbreviations (e.g. OCP, RHEL) in
            queries before searching (default False).
    """

    base_url: str = _DEFAULT_BASE_URL
    solr_handler: str = _DEFAULT_SOLR_HANDLER
    rows: int = _DEFAULT_ROWS
    timeout_connect: float = _DEFAULT_TIMEOUT_CONNECT
    timeout_read: float = _DEFAULT_TIMEOUT_READ
    timeout_pool: float = _DEFAULT_TIMEOUT_POOL
    retries: int = _DEFAULT_RETRIES
    verify_ssl: bool | str = True
    max_query_length: int = _MAX_QUERY_LENGTH
    max_context_chars: int = 0
    circuit_failure_threshold: int = 0
    circuit_reset_timeout: float = 30.0
    retry_max_attempts: int = 0
    retry_backoff_base: float = 0.5
    retry_backoff_max: float = 8.0
    cache_ttl: float = 0.0
    cache_max_entries: int = 256
    expand_synonyms: bool = False

    def __post_init__(self) -> None:
        errors: list[str] = []

        if not self.base_url:
            errors.append("base_url must be a non-empty string")
        if not self.solr_handler:
            errors.append("solr_handler must be a non-empty string")
        if self.rows < 1 or self.rows > _MAX_ROWS:
            errors.append(f"rows must be 1-{_MAX_ROWS}, got {self.rows}")
        if self.timeout_connect <= 0:
            errors.append(f"timeout_connect must be > 0, got {self.timeout_connect}")
        if self.timeout_read <= 0:
            errors.append(f"timeout_read must be > 0, got {self.timeout_read}")
        if self.timeout_pool <= 0:
            errors.append(f"timeout_pool must be > 0, got {self.timeout_pool}")
        if self.retries < 0:
            errors.append(f"retries must be >= 0, got {self.retries}")
        if self.max_query_length < 1:
            errors.append(f"max_query_length must be >= 1, got {self.max_query_length}")
        if self.max_context_chars < 0:
            errors.append(f"max_context_chars must be >= 0, got {self.max_context_chars}")
        if self.circuit_failure_threshold < 0:
            errors.append(
                f"circuit_failure_threshold must be >= 0, got {self.circuit_failure_threshold}"
            )
        if self.circuit_reset_timeout <= 0:
            errors.append(f"circuit_reset_timeout must be > 0, got {self.circuit_reset_timeout}")
        if self.retry_max_attempts < 0:
            errors.append(f"retry_max_attempts must be >= 0, got {self.retry_max_attempts}")
        if self.retry_backoff_base <= 0:
            errors.append(f"retry_backoff_base must be > 0, got {self.retry_backoff_base}")
        if self.retry_backoff_max <= 0:
            errors.append(f"retry_backoff_max must be > 0, got {self.retry_backoff_max}")
        if self.cache_ttl < 0:
            errors.append(f"cache_ttl must be >= 0, got {self.cache_ttl}")
        if self.cache_max_entries < 0:
            errors.append(f"cache_max_entries must be >= 0, got {self.cache_max_entries}")

        if errors:
            raise ValueError("Invalid OKP configuration: " + "; ".join(errors))

    @classmethod
    def from_env(cls, **overrides: object) -> OKPConfig:
        """Build config from environment variables with optional overrides.

        Environment variables:
            RHOKP_BASE_URL                 -- OKP base URL (default http://127.0.0.1:8080)
            RHOKP_SOLR_HANDLER             -- Solr handler path (default /solr/portal/select)
            RHOKP_RAG_ROWS                 -- Default rows (default 5)
            RHOKP_TIMEOUT_CONNECT          -- Connect timeout seconds (default 5.0)
            RHOKP_TIMEOUT_READ             -- Read timeout seconds (default 25.0)
            RHOKP_VERIFY_SSL               -- "true", "false", or path to CA bundle
            RHOKP_MAX_CONTEXT_CHARS        -- Max context chars (default 0 = unlimited)
            RHOKP_CIRCUIT_FAILURE_THRESHOLD -- Failures to open circuit (default 0 = off)
            RHOKP_CIRCUIT_RESET_TIMEOUT    -- Seconds before half-open (default 30)
            RHOKP_RETRY_MAX_ATTEMPTS       -- App-level retries (default 0 = off)
            RHOKP_CACHE_TTL                -- Cache TTL seconds (default 0 = off)
            RHOKP_EXPAND_SYNONYMS          -- Expand RH abbreviations (default false)

        Explicit keyword arguments override environment variables.
        """

        def _env(key: str, default: str) -> str:
            return os.environ.get(key, default)

        def _env_float(key: str, default: float) -> float:
            raw = os.environ.get(key)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"Environment variable {key}={raw!r} is not a valid number")

        def _env_int(key: str, default: int) -> int:
            raw = os.environ.get(key)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"Environment variable {key}={raw!r} is not a valid integer")

        def _env_verify(key: str, default: bool | str) -> bool | str:
            raw = os.environ.get(key)
            if raw is None:
                return default
            low = raw.strip().lower()
            if low in ("true", "1", "yes"):
                return True
            if low in ("false", "0", "no"):
                return False
            return raw  # treat as CA bundle path

        kwargs: dict[str, object] = {
            "base_url": _env("RHOKP_BASE_URL", _DEFAULT_BASE_URL).rstrip("/"),
            "solr_handler": _env("RHOKP_SOLR_HANDLER", _DEFAULT_SOLR_HANDLER),
            "rows": _env_int("RHOKP_RAG_ROWS", _DEFAULT_ROWS),
            "timeout_connect": _env_float("RHOKP_TIMEOUT_CONNECT", _DEFAULT_TIMEOUT_CONNECT),
            "timeout_read": _env_float("RHOKP_TIMEOUT_READ", _DEFAULT_TIMEOUT_READ),
            "timeout_pool": _env_float("RHOKP_TIMEOUT_POOL", _DEFAULT_TIMEOUT_POOL),
            "retries": _env_int("RHOKP_RETRIES", _DEFAULT_RETRIES),
            "verify_ssl": _env_verify("RHOKP_VERIFY_SSL", True),
            "max_context_chars": _env_int("RHOKP_MAX_CONTEXT_CHARS", 0),
            "circuit_failure_threshold": _env_int("RHOKP_CIRCUIT_FAILURE_THRESHOLD", 0),
            "circuit_reset_timeout": _env_float("RHOKP_CIRCUIT_RESET_TIMEOUT", 30.0),
            "retry_max_attempts": _env_int("RHOKP_RETRY_MAX_ATTEMPTS", 0),
            "retry_backoff_base": _env_float("RHOKP_RETRY_BACKOFF_BASE", 0.5),
            "retry_backoff_max": _env_float("RHOKP_RETRY_BACKOFF_MAX", 8.0),
            "cache_ttl": _env_float("RHOKP_CACHE_TTL", 0.0),
            "cache_max_entries": _env_int("RHOKP_CACHE_MAX_ENTRIES", 256),
            "expand_synonyms": _env_verify("RHOKP_EXPAND_SYNONYMS", False),
        }
        kwargs.update({k: v for k, v in overrides.items() if v is not None})

        config = cls(**kwargs)  # type: ignore[arg-type]
        logger.info(
            "OKP config: base_url=%s handler=%s rows=%d timeout_connect=%.1f"
            " timeout_read=%.1f retries=%d",
            config.base_url,
            config.solr_handler,
            config.rows,
            config.timeout_connect,
            config.timeout_read,
            config.retries,
        )
        return config
