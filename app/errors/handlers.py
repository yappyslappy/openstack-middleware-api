from __future__ import annotations

from flask import Flask, current_app, jsonify
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """Base exception for client-safe API errors."""

    status_code = 500
    message = "Internal server error."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class BadRequest(ApiError):
    """Bad request error."""

    status_code = 400
    message = "Bad request."


class Unauthorized(ApiError):
    """Unauthorized error."""

    status_code = 401
    message = "Unauthorized."


class Forbidden(ApiError):
    """Forbidden error."""

    status_code = 403
    message = "Forbidden."


class NotFound(ApiError):
    """Not found error."""

    status_code = 404
    message = "Resource not found."


class UpstreamError(ApiError):
    """OpenStack upstream failure."""

    status_code = 502
    message = "Upstream service error."


class ServiceUnavailable(ApiError):
    """Local service unavailable failure."""

    status_code = 503
    message = "Service unavailable."


class UpstreamUnavailable(ServiceUnavailable):
    """OpenStack upstream unavailable failure."""

    message = "Upstream service unavailable."


class GatewayTimeout(ApiError):
    """OpenStack upstream timeout."""

    status_code = 504
    message = "Upstream request timed out."


def register_error_handlers(app: Flask) -> None:
    """Register API error handlers."""

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError) -> ResponseReturnValue:
        return error_response(error.message, error.status_code)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException) -> ResponseReturnValue:
        code = error.code or 500
        message = _http_message(code)
        return error_response(message, code)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception) -> ResponseReturnValue:
        current_app.logger.error(
            "unhandled_exception",
            extra={"error_type": type(error).__name__},
        )
        return error_response("Internal server error.", 500)


def error_response(message: str, code: int) -> ResponseReturnValue:
    """Build a standardized error JSON response."""
    return jsonify({"status": "error", "message": message, "code": code}), code


def _http_message(code: int) -> str:
    messages = {
        400: "Bad request.",
        404: "Resource not found.",
        405: "Method not allowed.",
    }
    return messages.get(code, "Request failed.")
