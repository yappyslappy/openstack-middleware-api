from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from flask import Flask
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.session import get_inventory_session_factory
from app.errors.handlers import BadRequest, Conflict, NotFound, ServiceUnavailable
from app.repositories.inventory import (
    CollectionResult,
    InventoryRepository,
    InventoryResourceAmbiguous,
    InventoryResourceNotFound,
)

SOURCE_FILTER_LIMITS = {
    "scope": 128,
    "project_id": 128,
    "project_name": 255,
    "region": 255,
}
STRICT_SOURCE_FILTER = re.compile(r"^[A-Za-z0-9_.:-]+$")


@dataclass(frozen=True, slots=True)
class InventoryResponse:
    """Data plus optional response metadata."""

    data: Any
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SortOptions:
    """Validated sort options."""

    field: str
    descending: bool


class InventoryQueryService:
    """API-facing read service backed by the global inventory database."""

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        logger: logging.Logger | None = None,
    ) -> None:
        settings.validate_inventory()
        self._max_age_seconds = settings.inventory_max_age_seconds
        self._session_factory = session_factory
        self._logger = logger or logging.getLogger(__name__)

    def health(self) -> InventoryResponse:
        """Return application, database, and global inventory sync health."""

        def query(repository: InventoryRepository) -> InventoryResponse:
            repository.check_database()
            sources = repository.list_inventory_sources().items
            if not sources:
                raise ServiceUnavailable("No active inventory sources are available.")
            return InventoryResponse(self._health_payload(sources))

        return self._run("health", query)

    def list_inventory_sources(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return safe active source metadata."""
        source_filters = _source_filters(args)

        def query(repository: InventoryRepository) -> InventoryResponse:
            result = repository.list_inventory_sources(source_filters)
            data = [_normalize_inventory_source(row) for row in result.items]
            return InventoryResponse(data, _count_meta(result))

        return self._run("list_inventory_sources", query)

    def list_projects(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return active projects across all active inventory sources."""
        source_filters = _source_filters(args)
        sort = _sort(args, allowed={"id", "name"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            result = repository.list_projects(
                source_filters, sort.field, sort.descending
            )
            data = [_normalize_project(row) for row in result.items]
            return InventoryResponse(data, _count_meta(result))

        return self._run("list_projects", query)

    def list_servers(
        self, args: Mapping[str, str], tags: Sequence[str]
    ) -> InventoryResponse:
        """Return active servers across all active inventory sources."""
        source_filters = _source_filters(args)
        sort = _sort(
            args,
            allowed={
                "id",
                "name",
                "status",
                "project_id",
                "availability_zone",
                "compute_host",
                "power_state",
                "vm_state",
            },
            default="name",
        )
        resource_filters = _server_filters(args)

        def query(repository: InventoryRepository) -> InventoryResponse:
            result = repository.list_servers(
                source_filters,
                resource_filters,
                tags,
                sort.field,
                sort.descending,
            )
            data = [_normalize_server(row) for row in result.items]
            return InventoryResponse(data, _count_meta(result))

        return self._run("list_servers", query)

    def get_server(self, server_id: str, args: Mapping[str, str]) -> InventoryResponse:
        """Return one active server, requiring disambiguation when needed."""
        source_filters = _source_filters(args)

        def query(repository: InventoryRepository) -> InventoryResponse:
            server = repository.get_server(server_id, source_filters)
            return InventoryResponse(_normalize_server(server))

        return self._run(
            "get_server",
            query,
            not_found_message="Inventory server was not found.",
        )

    def list_networks(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return active networks across all active inventory sources."""
        source_filters = _source_filters(args)
        sort = _sort(args, allowed={"id", "name", "status"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            result = repository.list_networks(
                source_filters, sort.field, sort.descending
            )
            data = [_normalize_network(row) for row in result.items]
            return InventoryResponse(data, _count_meta(result))

        return self._run("list_networks", query)

    def list_images(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return active images across all active inventory sources."""
        source_filters = _source_filters(args)
        sort = _sort(args, allowed={"id", "name", "status"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            result = repository.list_images(source_filters, sort.field, sort.descending)
            data = [_normalize_image(row) for row in result.items]
            return InventoryResponse(data, _count_meta(result))

        return self._run("list_images", query)

    def list_flavors(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return active flavors across all active inventory sources."""
        source_filters = _source_filters(args)
        sort = _sort(args, allowed={"id", "name"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            result = repository.list_flavors(
                source_filters, sort.field, sort.descending
            )
            data = [_normalize_flavor(row) for row in result.items]
            return InventoryResponse(data, _count_meta(result))

        return self._run("list_flavors", query)

    def _run(
        self,
        operation: str,
        query: Callable[[InventoryRepository], InventoryResponse],
        *,
        not_found_message: str = "Inventory resource was not found.",
    ) -> InventoryResponse:
        try:
            with self._session_factory() as session:
                repository = InventoryRepository(session)
                return query(repository)
        except InventoryResourceAmbiguous as error:
            raise Conflict(
                "Server ID matches multiple inventory sources; add a scope query "
                "parameter."
            ) from error
        except InventoryResourceNotFound as error:
            raise NotFound(not_found_message) from error
        except SQLAlchemyError as error:
            self._logger.warning(
                "inventory_database_operation_failed",
                extra={"operation": operation, "error_type": type(error).__name__},
            )
            raise ServiceUnavailable("Inventory database is unavailable.") from error

    def _health_payload(self, sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        now = datetime.now(UTC)
        stale_scopes: list[str] = []
        failed_scopes: list[str] = []
        successful_syncs: list[datetime] = []

        for source in sources:
            scope = _string(source["scope_key"])
            last_success = _utc_datetime(source["last_successful_sync_at"])
            last_failure = _utc_datetime(source["last_failed_sync_at"])
            if last_success is None:
                stale_scopes.append(scope)
            else:
                successful_syncs.append(last_success)
                age_seconds = int((now - last_success).total_seconds())
                if age_seconds > self._max_age_seconds:
                    stale_scopes.append(scope)

            if last_failure is not None and (
                last_success is None or last_failure >= last_success
            ):
                failed_scopes.append(scope)

        return {
            "application": "healthy",
            "database": "healthy",
            "active_inventory_sources": len(sources),
            "stale_inventory_sources": len(stale_scopes),
            "stale_inventory_scopes": stale_scopes,
            "failed_inventory_sources": len(failed_scopes),
            "failed_inventory_scopes": failed_scopes,
            "oldest_successful_sync_at": (
                _datetime_string(min(successful_syncs)) if successful_syncs else None
            ),
            "newest_successful_sync_at": (
                _datetime_string(max(successful_syncs)) if successful_syncs else None
            ),
        }


def create_inventory_query_service(app: Flask) -> InventoryQueryService:
    """Create an inventory query service for a Flask app."""
    settings = cast(Settings, app.config["SETTINGS"])
    return InventoryQueryService(
        settings=settings,
        session_factory=get_inventory_session_factory(app),
        logger=app.logger,
    )


def _source_filters(args: Mapping[str, str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for key, max_length in SOURCE_FILTER_LIMITS.items():
        raw_value = args.get(key)
        if raw_value is None:
            continue
        value = _validated_query_value(key, raw_value, max_length)
        if key in {"scope", "project_id", "region"} and not STRICT_SOURCE_FILTER.match(
            value
        ):
            raise BadRequest(f"{key} filter contains unsupported characters.")
        filters[key] = value
    return filters


def _validated_query_value(name: str, value: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise BadRequest(f"{name} filter must be non-empty.")
    if len(normalized) > max_length:
        raise BadRequest(f"{name} filter must be {max_length} characters or fewer.")
    if any(_is_control_character(character) for character in normalized):
        raise BadRequest(f"{name} filter must not contain control characters.")
    return normalized


def _sort(args: Mapping[str, str], *, allowed: set[str], default: str) -> SortOptions:
    sort_field = args.get("sort") or default
    if sort_field not in allowed:
        raise BadRequest("Unsupported sort field.")

    order = (args.get("order") or "asc").lower()
    if order not in {"asc", "desc"}:
        raise BadRequest("Sort order must be 'asc' or 'desc'.")
    return SortOptions(field=sort_field, descending=order == "desc")


def _server_filters(args: Mapping[str, str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for key in (
        "name",
        "status",
        "project_id",
        "availability_zone",
        "compute_host",
        "power_state",
        "vm_state",
    ):
        raw_value = args.get(key)
        if raw_value is None:
            continue
        filters[key] = _validated_query_value(key, raw_value, 255)
    return filters


def _count_meta(result: CollectionResult) -> dict[str, Any]:
    return {"count": result.total}


def _normalize_inventory_source(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _optional_int(row["id"]),
        "scope": _string(row["scope_key"]),
        "openstack_project_id": _optional_string(row["openstack_project_id"]),
        "openstack_project_name": _optional_string(row["openstack_project_name"]),
        "region_name": _optional_string(row["region_name"]),
        "last_successful_sync_at": _datetime_string(row["last_successful_sync_at"]),
        "last_failed_sync_at": _datetime_string(row["last_failed_sync_at"]),
    }


def _normalize_project(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row["id"]),
        "name": _string(row["name"]),
        "description": _optional_string(row["description"]),
        "enabled": _optional_bool(row["is_enabled"]),
        "domain_id": _optional_string(row["domain_id"]),
        "inventory_source": _source_identity(row),
    }


def _normalize_server(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row["id"]),
        "name": _string(row["name"]),
        "status": _optional_string(row["status"]),
        "project_id": _optional_string(row["project_id"]),
        "flavor": _optional_string(row["flavor_id"]),
        "image": _optional_string(row["image_id"]),
        "addresses": _addresses(row),
        "tags": _string_list(row["tags"]),
        "created_at": _datetime_string(row["resource_created_at"]),
        "updated_at": _datetime_string(row["resource_updated_at"]),
        "inventory_source": _source_identity(row),
    }


def _normalize_network(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row["id"]),
        "name": _string(row["name"]),
        "status": _optional_string(row["status"]),
        "project_id": _optional_string(row["project_id"]),
        "mtu": _optional_int(row["mtu"]),
        "admin_state_up": _optional_bool(row["admin_state_up"]),
        "is_shared": _optional_bool(row["is_shared"]),
        "is_router_external": _optional_bool(row["is_router_external"]),
        "provider_network_type": _optional_string(row["provider_network_type"]),
        "provider_physical_network": _optional_string(row["provider_physical_network"]),
        "provider_segmentation_id": _optional_int(row["provider_segmentation_id"]),
        "created_at": _datetime_string(row["resource_created_at"]),
        "updated_at": _datetime_string(row["resource_updated_at"]),
        "inventory_source": _source_identity(row),
    }


def _normalize_image(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row["id"]),
        "name": _string(row["name"]),
        "status": _optional_string(row["status"]),
        "visibility": _optional_string(row["visibility"]),
        "container_format": _optional_string(row["container_format"]),
        "disk_format": _optional_string(row["disk_format"]),
        "min_disk": _optional_int(row["min_disk"]),
        "min_ram": _optional_int(row["min_ram"]),
        "size_bytes": _optional_int(row["size_bytes"]),
        "checksum": _optional_string(row["checksum"]),
        "created_at": _datetime_string(row["resource_created_at"]),
        "updated_at": _datetime_string(row["resource_updated_at"]),
        "inventory_source": _source_identity(row),
    }


def _normalize_flavor(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row["id"]),
        "name": _string(row["name"]),
        "vcpus": _optional_int(row["vcpus"]),
        "ram_mb": _optional_int(row["ram_mb"]),
        "disk_gb": _optional_int(row["disk_gb"]),
        "ephemeral_gb": _optional_int(row["ephemeral_gb"]),
        "swap_mb": _optional_int(row["swap_mb"]),
        "is_public": _optional_bool(row["is_public"]),
        "created_at": _datetime_string(row["resource_created_at"]),
        "updated_at": _datetime_string(row["resource_updated_at"]),
        "inventory_source": _source_identity(row),
    }


def _source_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _optional_int(row["source_id"]),
        "scope": _string(row["source_scope"]),
        "project_id": _optional_string(row["source_openstack_project_id"]),
        "project_name": _optional_string(row["source_openstack_project_name"]),
        "region_name": _optional_string(row["source_region_name"]),
    }


def _addresses(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = row["normalized_addresses"]
    if isinstance(normalized, Mapping) and normalized:
        return dict(normalized)

    addresses = row["addresses"]
    if isinstance(addresses, Mapping):
        return dict(addresses)
    return {}


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


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [str(item) for item in value]
    return []


def _datetime_string(value: Any) -> str | None:
    timestamp = _utc_datetime(value)
    if timestamp is None:
        return None
    return timestamp.isoformat().replace("+00:00", "Z")


def _utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _is_control_character(character: str) -> bool:
    codepoint = ord(character)
    return codepoint < 32 or codepoint == 127
