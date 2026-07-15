from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app, request
from flask.typing import ResponseReturnValue

from app.config import Settings
from app.errors.handlers import BadRequest
from app.services.inventory_query import (
    InventoryQueryService,
    InventoryResponse,
    create_inventory_query_service,
)
from app.services.openstack_client import OpenStackClient, OpenStackService
from app.utils import success_response

MAX_TAG_LENGTH = 128

bp = Blueprint("openstack", __name__, url_prefix="/api/v1")


@bp.get("/projects")
def list_projects() -> ResponseReturnValue:
    """Return inventory projects from active sources."""
    return _inventory_success(_inventory_query_service().list_projects(request.args))


@bp.get("/inventory-sources")
def list_inventory_sources() -> ResponseReturnValue:
    """Return active inventory source metadata."""
    return _inventory_success(
        _inventory_query_service().list_inventory_sources(request.args)
    )


@bp.get("/servers")
def list_servers() -> ResponseReturnValue:
    """Return inventory servers, optionally filtered by tags."""
    tags = _validate_tags(request.args.getlist("tag"))
    return _inventory_success(
        _inventory_query_service().list_servers(request.args, tags)
    )


@bp.get("/servers/<server_id>")
def get_server(server_id: str) -> ResponseReturnValue:
    """Return one inventory server by ID."""
    return _inventory_success(
        _inventory_query_service().get_server(server_id, request.args)
    )


@bp.get("/networks")
def list_networks() -> ResponseReturnValue:
    """Return inventory networks from active sources."""
    return _inventory_success(_inventory_query_service().list_networks(request.args))


@bp.get("/images")
def list_images() -> ResponseReturnValue:
    """Return inventory images from active sources."""
    return _inventory_success(_inventory_query_service().list_images(request.args))


@bp.get("/flavors")
def list_flavors() -> ResponseReturnValue:
    """Return inventory flavors from active sources."""
    return _inventory_success(_inventory_query_service().list_flavors(request.args))


def _inventory_success(response: InventoryResponse) -> ResponseReturnValue:
    return success_response(response.data, meta=response.meta)


def _inventory_query_service() -> InventoryQueryService:
    service = current_app.extensions.get("inventory_query_service")
    if service is None:
        service = create_inventory_query_service(current_app)
        current_app.extensions["inventory_query_service"] = service
    return cast(InventoryQueryService, service)


def _openstack_service() -> OpenStackService:
    service = current_app.extensions.get("openstack_service")
    if service is None:
        settings = cast(Settings, current_app.config["SETTINGS"])
        service = OpenStackClient(settings)
        current_app.extensions["openstack_service"] = service
    return cast(OpenStackService, service)


def _validate_tags(raw_tags: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    for raw_tag in raw_tags:
        tag = _validate_tag(raw_tag)
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)

    return tags


def _validate_tag(tag: str) -> str:
    normalized = tag.strip()
    if not normalized:
        raise BadRequest("Server tag must be non-empty.")
    if len(normalized) > MAX_TAG_LENGTH:
        raise BadRequest(f"Server tag must be {MAX_TAG_LENGTH} characters or fewer.")
    if any(_is_control_character(character) for character in normalized):
        raise BadRequest("Server tag must not contain control characters.")
    return normalized


def _is_control_character(character: str) -> bool:
    codepoint = ord(character)
    return codepoint < 32 or codepoint == 127
