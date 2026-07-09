from __future__ import annotations

import json
import logging
import time
from typing import Any

from flask import Flask, current_app, g, request


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured application logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for attribute in (
            "path",
            "method",
            "status_code",
            "duration_ms",
            "reason",
            "operation",
            "error_type",
        ):
            if hasattr(record, attribute):
                payload[attribute] = getattr(record, attribute)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(app: Flask) -> None:
    """Configure structured JSON logging for the Flask application."""
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    formatter = JsonFormatter()

    if not app.logger.handlers:
        app.logger.addHandler(logging.StreamHandler())

    for handler in app.logger.handlers:
        handler.setFormatter(formatter)


def register_request_logging(app: Flask) -> None:
    """Register request/response logging hooks."""

    @app.before_request
    def capture_request_start() -> None:
        g.request_start_time = time.perf_counter()

    @app.after_request
    def log_request(response: Any) -> Any:
        started_at = getattr(g, "request_start_time", time.perf_counter())
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        current_app.logger.info(
            "request_completed",
            extra={
                "path": request.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
