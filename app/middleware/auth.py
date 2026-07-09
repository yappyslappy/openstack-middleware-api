from __future__ import annotations

import hmac
from typing import Final, cast

from flask import Flask, current_app, request

from app.config import Settings
from app.errors.handlers import Forbidden, ServiceUnavailable, Unauthorized

PUBLIC_METHODS: Final[set[str]] = {"GET", "HEAD", "OPTIONS"}
PROTECTED_METHODS: Final[set[str]] = {"POST", "PUT", "PATCH", "DELETE"}


def register_auth_middleware(app: Flask) -> None:
    """Register method-based API key authentication middleware."""

    @app.before_request
    def require_api_key_for_mutations() -> None:
        if request.method in PUBLIC_METHODS:
            return
        if request.method not in PROTECTED_METHODS:
            return

        settings = cast(Settings, current_app.config["SETTINGS"])
        configured_api_key = settings.api_key
        if not configured_api_key:
            current_app.logger.error(
                "authentication_not_configured",
                extra={"path": request.path, "method": request.method},
            )
            raise ServiceUnavailable("Authentication service is not configured.")

        authorization = request.headers.get("Authorization")
        if authorization is None:
            _log_auth_failure("missing_authorization_header")
            raise Unauthorized("Authorization header is required.")

        token = _extract_bearer_token(authorization)
        if not hmac.compare_digest(token, configured_api_key):
            _log_auth_failure("invalid_api_key")
            raise Forbidden("Invalid API key.")


def _extract_bearer_token(authorization: str) -> str:
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        _log_auth_failure("invalid_authorization_header")
        raise Unauthorized("Bearer token is required.")
    return token.strip()


def _log_auth_failure(reason: str) -> None:
    current_app.logger.warning(
        "authentication_failed",
        extra={
            "path": request.path,
            "method": request.method,
            "reason": reason,
        },
    )
