"""
Structured logging for rhokp with request-id correlation.

Provides a JSON log formatter, request-id propagation via ``contextvars``,
and a convenience function to configure the ``rhokp`` logger hierarchy.

Usage::

    from rhokp.logging import configure_logging, bind_request_id
    configure_logging()            # JSON to stderr, INFO level
    bind_request_id("req-abc123")  # all subsequent logs include request_id
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

_request_id_var: ContextVar[str] = ContextVar("rhokp_request_id", default="")

_STDLIB_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


def bind_request_id(request_id: str | None = None) -> str:
    """Set the request-id for the current context (thread / async task).

    If *request_id* is ``None``, a new UUID4 is generated.
    Returns the active request-id.
    """
    rid = request_id or uuid.uuid4().hex[:12]
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    """Return the current request-id, or ``""`` if none is bound."""
    return _request_id_var.get()


class _RequestIdFilter(logging.Filter):
    """Inject ``request_id`` from the context-var into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        return True


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Core fields: ``timestamp``, ``level``, ``logger``, ``message``,
    ``request_id``. Any *extra* kwargs passed to ``logger.info(..., extra={})``
    are merged at the top level, so callers can add structured data without
    changing the formatter.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        rid = getattr(record, "request_id", "") or _request_id_var.get()
        if rid:
            entry["request_id"] = rid

        for key, val in record.__dict__.items():
            if key not in _STDLIB_ATTRS and key != "request_id":
                entry[key] = val

        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def configure_logging(
    level: int = logging.INFO,
    json_format: bool = True,
) -> None:
    """Configure the ``rhokp`` logger hierarchy.

    Args:
        level: Logging level (default ``logging.INFO``).
        json_format: If ``True``, emit JSON lines; if ``False``, use a
            human-friendly text format that still includes the request-id.
    """
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-5s [%(request_id)s] %(name)s - %(message)s",
                defaults={"request_id": ""},
            )
        )
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger("rhokp")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
