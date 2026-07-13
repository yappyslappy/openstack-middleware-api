from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app
from flask.typing import ResponseReturnValue

from app.services.inventory_query import (
    InventoryQueryService,
    create_inventory_query_service,
)
from app.utils import success_response

bp = Blueprint("health", __name__)


@bp.get("/health")
def health_check() -> ResponseReturnValue:
    """Return service health information."""
    response = _inventory_query_service().health()
    return success_response(response.data, meta=response.meta)


def _inventory_query_service() -> InventoryQueryService:
    service = current_app.extensions.get("inventory_query_service")
    if service is None:
        service = create_inventory_query_service(current_app)
        current_app.extensions["inventory_query_service"] = service
    return cast(InventoryQueryService, service)
