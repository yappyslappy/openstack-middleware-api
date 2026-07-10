from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol, TypeVar

from app.config import DEFAULT_OPENSTACK_AUTH_TYPE, ConfigurationError, Settings
from app.errors.handlers import (
    ApiError,
    GatewayTimeout,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)

T = TypeVar("T")


class OpenStackService(Protocol):
    """Protocol implemented by OpenStack service clients."""

    def list_projects(self) -> list[dict[str, Any]]:
        """Return visible OpenStack projects."""

    def list_servers(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """Return visible OpenStack servers, optionally filtered by tags."""

    def get_server(self, server_id: str) -> dict[str, Any]:
        """Return one OpenStack server by ID."""

    def list_networks(self) -> list[dict[str, Any]]:
        """Return visible OpenStack networks."""

    def list_images(self) -> list[dict[str, Any]]:
        """Return visible OpenStack images."""

    def list_flavors(self) -> list[dict[str, Any]]:
        """Return visible OpenStack flavors."""


class OpenStackClient:
    """OpenStack SDK wrapper that returns normalized API-safe data."""

    def __init__(
        self,
        settings: Settings,
        connection: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._connection = connection
        self._logger = logger or logging.getLogger(__name__)

    @property
    def connection(self) -> Any:
        """Return a cached OpenStack SDK connection."""
        if self._connection is None:
            self._connection = self._connect()
        return self._connection

    def list_projects(self) -> list[dict[str, Any]]:
        """Return projects visible to the service account."""
        projects = self._execute(
            "list_projects", lambda: list(self.connection.identity.projects())
        )
        return [_normalize_project(project) for project in projects]

    def list_servers(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """Return servers visible to the service account."""
        requested_tags = _dedupe_preserving_order(tags or [])
        query: dict[str, Any] = {"details": True}
        if requested_tags:
            query["tags"] = _server_tags_query(requested_tags)

        try:
            servers = list(self.connection.compute.servers(**query))
        except Exception as error:
            if requested_tags and _is_native_tag_filter_unsupported(error):
                servers = self._execute(
                    "list_servers_fallback",
                    lambda: list(self.connection.compute.servers(details=True)),
                )
                servers = [
                    server
                    for server in servers
                    if _resource_has_tags(server, requested_tags)
                ]
            else:
                self._raise_openstack_error("list_servers", error)
        else:
            if requested_tags:
                servers = [
                    server
                    for server in servers
                    if _resource_has_tags(server, requested_tags)
                ]

        return [_normalize_server(server) for server in servers]

    def get_server(self, server_id: str) -> dict[str, Any]:
        """Return one server by ID."""
        server = self._execute(
            "get_server", lambda: self.connection.compute.get_server(server_id)
        )
        if server is None:
            raise NotFound("OpenStack server was not found.")
        return _normalize_server(server)

    def list_networks(self) -> list[dict[str, Any]]:
        """Return networks visible to the service account."""
        networks = self._execute(
            "list_networks", lambda: list(self.connection.network.networks())
        )
        return [_normalize_network(network) for network in networks]

    def list_images(self) -> list[dict[str, Any]]:
        """Return images visible to the service account."""
        images = self._execute(
            "list_images", lambda: list(self.connection.image.images())
        )
        return [_normalize_image(image) for image in images]

    def list_flavors(self) -> list[dict[str, Any]]:
        """Return flavors visible to the service account."""
        flavors = self._execute(
            "list_flavors", lambda: list(self.connection.compute.flavors())
        )
        return [_normalize_flavor(flavor) for flavor in flavors]

    def _connect(self) -> Any:
        try:
            kwargs: dict[str, Any] = {
                **self._build_auth_config(),
                "identity_api_version": self._settings.os_identity_api_version,
                "app_name": "openstack-middleware-api",
                "app_version": "0.1.0",
                "connect_retries": 2,
                "timeout": 30,
            }
        except ConfigurationError as error:
            self._logger.error(
                "openstack_configuration_invalid",
                extra={"error_type": type(error).__name__},
            )
            raise UpstreamUnavailable("OpenStack service is not configured.") from error

        if self._settings.os_region_name:
            kwargs["region_name"] = self._settings.os_region_name
        if self._settings.os_interface:
            kwargs["interface"] = self._settings.os_interface

        return self._execute("connect", lambda: openstack_connect(**kwargs))

    def _build_auth_config(self) -> dict[str, Any]:
        """Build OpenStack SDK auth kwargs for the selected auth mode."""
        self._settings.validate_openstack()
        auth_type = self._settings.resolved_openstack_auth_type

        if auth_type == DEFAULT_OPENSTACK_AUTH_TYPE:
            return {
                "auth_type": "v3applicationcredential",
                "auth": {
                    "auth_url": self._settings.os_auth_url or "",
                    "application_credential_id": (
                        self._settings.os_application_credential_id or ""
                    ),
                    "application_credential_secret": (
                        self._settings.os_application_credential_secret or ""
                    ),
                },
            }

        return {
            "auth_type": "v3password",
            "auth": {
                "auth_url": self._settings.os_auth_url or "",
                "username": self._settings.os_username or "",
                "password": self._settings.os_password or "",
                "user_domain_name": self._settings.os_user_domain_name or "",
                "project_name": self._settings.os_project_name or "",
                "project_domain_name": (self._settings.os_project_domain_name or ""),
            },
        }

    def _execute(self, operation: str, func: Callable[[], T]) -> T:
        try:
            return func()
        except ApiError:
            raise
        except Exception as error:
            self._raise_openstack_error(operation, error)

    def _raise_openstack_error(self, operation: str, error: Exception) -> NoReturn:
        self._logger.warning(
            "openstack_operation_failed",
            extra={
                "operation": operation,
                "error_type": type(error).__name__,
                "status_code": _status_code(error),
            },
        )
        raise _translate_openstack_error(error) from error


def openstack_connect(**kwargs: Any) -> Any:
    """Create an OpenStack SDK connection."""
    import openstack

    return openstack.connect(**kwargs)


def _translate_openstack_error(error: Exception) -> ApiError:
    status_code = _status_code(error)
    error_name = type(error).__name__.lower()

    if isinstance(error, TimeoutError) or "timeout" in error_name:
        return GatewayTimeout("OpenStack request timed out.")
    if status_code == 404 or "notfound" in error_name:
        return NotFound("OpenStack resource was not found.")
    if status_code == 401 or "unauthorized" in error_name:
        return UpstreamUnavailable("OpenStack authentication failed.")
    if status_code == 403 or "forbidden" in error_name:
        return UpstreamError(
            "OpenStack service account is not authorized for this request."
        )
    if "connect" in error_name or "endpoint" in error_name:
        return UpstreamUnavailable("OpenStack service is unavailable.")
    return UpstreamError("OpenStack request failed.")


def _is_native_tag_filter_unsupported(error: Exception) -> bool:
    if isinstance(error, TypeError):
        return True

    status_code = _status_code(error)
    message = str(error).lower()
    unsupported_status = status_code in {400, 406, 501}
    tag_related = "tag" in message or "unsupported" in message
    return unsupported_status and tag_related


def _status_code(error: Exception) -> int | None:
    for attribute in ("status_code", "http_status", "status"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value

    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


def _normalize_project(project: Any) -> dict[str, Any]:
    return {
        "id": _string(_value(project, "id")),
        "name": _string(_value(project, "name")),
        "description": _optional_string(_value(project, "description")),
        "enabled": _optional_bool(_value(project, "is_enabled", "enabled")),
        "domain_id": _optional_string(_value(project, "domain_id")),
    }


def _normalize_server(server: Any) -> dict[str, Any]:
    return {
        "id": _string(_value(server, "id")),
        "name": _string(_value(server, "name")),
        "status": _optional_string(_value(server, "status")),
        "project_id": _optional_string(_value(server, "project_id", "tenant_id")),
        "flavor": _name_from_reference(_value(server, "flavor")),
        "image": _name_from_reference(_value(server, "image")),
        "addresses": _mapping(_value(server, "addresses"), default={}),
        "tags": _string_list(_value(server, "tags"), default=[]),
        "created_at": _datetime_string(
            _value(server, "created_at", "created", "createdAt")
        ),
    }


def _normalize_network(network: Any) -> dict[str, Any]:
    return {
        "id": _string(_value(network, "id")),
        "name": _string(_value(network, "name")),
        "status": _optional_string(_value(network, "status")),
        "project_id": _optional_string(_value(network, "project_id", "tenant_id")),
        "is_router_external": _optional_bool(
            _value(network, "is_router_external", "router:external")
        ),
        "is_shared": _optional_bool(_value(network, "is_shared", "shared")),
        "subnets": _string_list(_value(network, "subnet_ids", "subnets"), default=[]),
    }


def _normalize_image(image: Any) -> dict[str, Any]:
    return {
        "id": _string(_value(image, "id")),
        "name": _string(_value(image, "name")),
        "status": _optional_string(_value(image, "status")),
        "visibility": _optional_string(_value(image, "visibility")),
        "size": _optional_int(_value(image, "size")),
        "min_disk": _optional_int(_value(image, "min_disk")),
        "min_ram": _optional_int(_value(image, "min_ram")),
        "created_at": _datetime_string(_value(image, "created_at", "created_at")),
    }


def _normalize_flavor(flavor: Any) -> dict[str, Any]:
    return {
        "id": _string(_value(flavor, "id")),
        "name": _string(_value(flavor, "name")),
        "vcpus": _optional_int(_value(flavor, "vcpus")),
        "ram": _optional_int(_value(flavor, "ram")),
        "disk": _optional_int(_value(flavor, "disk")),
        "is_public": _optional_bool(_value(flavor, "is_public")),
    }


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _server_tags_query(tags: list[str]) -> str:
    return ",".join(tags)


def _resource_has_tags(resource: Any, tags: list[str]) -> bool:
    resource_tags = set(_string_list(_value(resource, "tags"), default=[]))
    return all(tag in resource_tags for tag in tags)


def _value(resource: Any, *names: str, default: Any = None) -> Any:
    if isinstance(resource, Mapping):
        for name in names:
            if name in resource:
                return resource[name]

    getter = getattr(resource, "get", None)
    if callable(getter):
        missing = object()
        for name in names:
            value = getter(name, missing)
            if value is not missing:
                return value

    for name in names:
        if hasattr(resource, name):
            return getattr(resource, name)

    return default


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


def _mapping(value: Any, default: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return default


def _string_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return default
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [str(item) for item in value]
    return default


def _name_from_reference(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    for name in ("original_name", "name", "id"):
        found = _value(value, name)
        if found is not None:
            return str(found)
    return str(value)


def _datetime_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        formatted = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return str(formatted)
    return str(value)
