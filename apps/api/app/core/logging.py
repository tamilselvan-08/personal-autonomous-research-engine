"""Structured logging with request correlation and secret redaction."""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_SENSITIVE_KEYS = re.compile(r"(authorization|api[_-]?key|cookie|password|secret|token)", re.I)
_SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI/Anthropic-style keys
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # Google API keys
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWTs
]


def redact(value: str) -> str:
    for pattern in _SECRET_VALUE_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def _redact_obj(obj: object) -> object:
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]" if _SENSITIVE_KEYS.search(str(k)) else _redact_obj(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


class JsonFormatter(logging.Formatter):
    _RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if rid := request_id_var.get():
            payload["request_id"] = rid
        if uid := user_id_var.get():
            payload["user_id"] = uid
        extras = {k: v for k, v in vars(record).items() if k not in self._RESERVED}
        if extras:
            payload.update(_redact_obj(extras))  # type: ignore[arg-type]
        if record.exc_info:
            payload["exc_info"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        base = super().format(record)
        return redact(f"{base} [request_id={rid}]" if rid else base)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
