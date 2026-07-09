from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app, request
from flask.typing import ResponseReturnValue

from app.config import Settings
from app.errors.handlers import BadRequest
from app.services.openstack_client import OpenStackClient, OpenStackService
from app.utils import success_response

MAX_TAG_LENGTH = 128

bp = Blueprint("openstack", __name__, url_prefix="/api/v1")


@bp.get("/projects")
def list_projects() -> ResponseReturnValue:
    """Return OpenStack projects visible to the service account."""
    return success_response(_openstack_service().list_projects())


@bp.get("/servers")
def list_servers() -> ResponseReturnValue:
    """Return OpenStack servers, optionally filtered by a tag."""
    tag = _validate_tag(request.args.get("tag"))
    return success_response(_openstack_service().list_servers(tag=tag))


@bp.get("/servers/<server_id>")
def get_server(server_id: str) -> ResponseReturnValue:
    """Return one OpenStack server by ID."""
    return success_response(_openstack_service().get_server(server_id))


@bp.get("/networks")
def list_networks() -> ResponseReturnValue:
    """Return OpenStack networks visible to the service account."""
    return success_response(_openstack_service().list_networks())


@bp.get("/images")
def list_images() -> ResponseReturnValue:
    """Return OpenStack images visible to the service account."""
    return success_response(_openstack_service().list_images())


@bp.get("/flavors")
def list_flavors() -> ResponseReturnValue:
    """Return OpenStack flavors visible to the service account."""
    return success_response(_openstack_service().list_flavors())


def _openstack_service() -> OpenStackService:
    service = current_app.extensions.get("openstack_service")
    if service is None:
        settings = cast(Settings, current_app.config["SETTINGS"])
        service = OpenStackClient(settings)
        current_app.extensions["openstack_service"] = service
    return cast(OpenStackService, service)


def _validate_tag(tag: str | None) -> str | None:
    if tag is None:
        return None

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
