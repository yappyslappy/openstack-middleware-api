from __future__ import annotations

from flask import Blueprint
from flask.typing import ResponseReturnValue

from app.utils import success_response

bp = Blueprint("health", __name__)


@bp.get("/health")
def health_check() -> ResponseReturnValue:
    """Return service health information."""
    return success_response(
        {
            "service": "openstack-middleware-api",
            "status": "ok",
        }
    )
