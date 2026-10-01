"""Structured logging in OpenTelemetry's log-record vocabulary.

Emits one JSON object per line. Field names follow the OTel data model so
that adding the SDK later needs no changes to call sites.
"""

import json
import logging
import sys
import warnings
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Correlation id for the current request or job. Set once at the boundary,
# read by every log record beneath it.
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# OTel severity numbers. Numeric so tooling can filter on ranges.
_SEVERITY_NUMBER = {
    "DEBUG": 5,
    "INFO": 9,
    "WARNING": 13,
    "ERROR": 17,
    "CRITICAL": 21,
}

# LogRecord attributes we never copy into the payload: they are either
# already mapped or are noise.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "color_message",
}


class OtelJsonFormatter(logging.Formatter):
    """Renders a LogRecord as a single-line JSON object."""

    def __init__(self, service_name: str, environment: str) -> None:
        super().__init__()
        self._service_name = service_name
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity_text": record.levelname,
            "severity_number": _SEVERITY_NUMBER.get(record.levelname, 0),
            "body": record.getMessage(),
            "service.name": self._service_name,
            "deployment.environment": self._environment,
            "code.namespace": record.name,
            "code.function": record.funcName,
            "code.lineno": record.lineno,
        }

        current = correlation_id.get()
        if current is not None:
            payload["correlation_id"] = current

        if record.exc_info:
            payload["exception.type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exception.stacktrace"] = self.formatException(record.exc_info)

        # Uvicorn access records carry the useful values in args; promoting
        # them makes status and route queryable instead of buried in a string.
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            if len(record.args) == 5:
                client, method, path, _http_version, status = record.args
                payload["body"] = "http request"
                payload["client.address"] = client
                payload["http.request.method"] = method
                payload["url.path"] = path
                payload["http.response.status_code"] = status

        # Anything passed via extra= becomes a first-class field.
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        return json.dumps(payload, default=str, ensure_ascii=False)


def _silence_library_warnings() -> None:
    """Third-party deprecation notices bypass logging entirely, writing to
    stderr as Python warnings. They are noise we do not act on."""
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning, module="torch")


def configure(service_name: str, level: str = "INFO", environment: str = "prod") -> None:
    """Install the JSON formatter as the only root handler. Idempotent."""
    # stderr, so stdout stays a clean channel for program output.
    _silence_library_warnings()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(OtelJsonFormatter(service_name, environment))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Third-party noise stays at WARNING so it cannot drown our own records.
    # Chatty at INFO; their warnings are still worth seeing.
    for noisy in ("httpx", "httpcore", "LiteLLM", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Phonemizer warns on every unusual word (product names, versions). The
    # warning is not actionable, so it needs ERROR rather than WARNING.
    logging.getLogger("phonemizer").setLevel(logging.CRITICAL)

    # Uvicorn installs its own handlers; clearing them makes its records
    # propagate to root and pick up the JSON formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
