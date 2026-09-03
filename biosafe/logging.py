"""Structured logging with credential redaction."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[-_]?key|token|password)(\s*[:=]\s*)(bearer\s+)?([^\s,;&]+)"
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {"authorization", "api_key", "token", "password", "token_secret"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in ("request_id", "session_id", "stage", "error_code", "details"):
            if hasattr(record, key):
                payload[key] = redact(getattr(record, key))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", log_file: Path | str | None = None) -> None:
    formatter = JsonFormatter()
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stream_handler]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root = logging.getLogger()
    for existing_handler in root.handlers:
        existing_handler.close()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
