from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Any, cast

from flask import Flask
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.session import get_inventory_session_factory
from app.errors.handlers import BadRequest, NotFound, ServiceUnavailable
from app.repositories.inventory import (
    InventoryRepository,
    InventoryResourceNotFound,
    InventorySource,
    InventorySourceNotFound,
    PageResult,
    Pagination,
)

MAX_PER_PAGE = 500
DEFAULT_PER_PAGE = 100


@dataclass(frozen=True, slots=True)
class InventoryResponse:
    """Data plus optional response metadata."""

    data: Any
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RequestPagination:
    """Validated request pagination."""

    repository: Pagination
    include_meta: bool


@dataclass(frozen=True, slots=True)
class SortOptions:
    """Validated sort options."""

    field: str
    descending: bool


class InventoryQueryService:
    """API-facing read service backed by the inventory database."""

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        logger: logging.Logger | None = None,
    ) -> None:
        settings.validate_inventory()
        self._inventory_scope = cast(str, settings.inventory_scope)
        self._max_age_seconds = settings.inventory_max_age_seconds
        self._session_factory = session_factory
        self._logger = logger or logging.getLogger(__name__)

    def health(self) -> InventoryResponse:
        """Return application, database, and inventory sync health."""

        def query(repository: InventoryRepository) -> InventoryResponse:
            repository.check_database()
            source = repository.get_active_source()
            freshness = self._freshness(source)
            return InventoryResponse(
                {
                    "application": "healthy",
                    "database": "healthy",
                    "inventory_scope": source.scope_key,
                    "last_successful_sync_at": _datetime_string(
                        source.last_successful_sync_at
                    ),
                    "inventory_age_seconds": freshness["inventory_age_seconds"],
                    "inventory_stale": freshness["inventory_stale"],
                }
            )

        return self._run("health", query)

    def list_projects(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return scoped active projects."""
        pagination = _pagination(args)
        sort = _sort(args, allowed={"id", "name"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            source = repository.get_active_source()
            page = repository.list_projects(
                source, pagination.repository, sort.field, sort.descending
            )
            return InventoryResponse(
                [_normalize_project(row) for row in page.items],
                self._collection_meta(page) if pagination.include_meta else None,
            )

        return self._run("list_projects", query)

    def list_servers(
        self, args: Mapping[str, str], tags: Sequence[str]
    ) -> InventoryResponse:
        """Return scoped active servers, optionally filtered by tags."""
        pagination = _pagination(args)
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
        filters = _server_filters(args)

        def query(repository: InventoryRepository) -> InventoryResponse:
            source = repository.get_active_source()
            page = repository.list_servers(
                source,
                pagination.repository,
                filters,
                tags,
                sort.field,
                sort.descending,
            )
            return InventoryResponse(
                [_normalize_server(row) for row in page.items],
                self._collection_meta(page) if pagination.include_meta else None,
            )

        return self._run("list_servers", query)

    def get_server(self, server_id: str) -> InventoryResponse:
        """Return a single scoped active server."""

        def query(repository: InventoryRepository) -> InventoryResponse:
            source = repository.get_active_source()
            server = repository.get_server(source, server_id)
            return InventoryResponse(_normalize_server(server))

        return self._run(
            "get_server",
            query,
            not_found_message="Inventory server was not found.",
        )

    def list_networks(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return scoped active networks."""
        pagination = _pagination(args)
        sort = _sort(args, allowed={"id", "name", "status"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            source = repository.get_active_source()
            page = repository.list_networks(
                source, pagination.repository, sort.field, sort.descending
            )
            return InventoryResponse(
                [_normalize_network(row) for row in page.items],
                self._collection_meta(page) if pagination.include_meta else None,
            )

        return self._run("list_networks", query)

    def list_images(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return scoped active images."""
        pagination = _pagination(args)
        sort = _sort(args, allowed={"id", "name", "status"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            source = repository.get_active_source()
            page = repository.list_images(
                source, pagination.repository, sort.field, sort.descending
            )
            return InventoryResponse(
                [_normalize_image(row) for row in page.items],
                self._collection_meta(page) if pagination.include_meta else None,
            )

        return self._run("list_images", query)

    def list_flavors(self, args: Mapping[str, str]) -> InventoryResponse:
        """Return scoped active flavors."""
        pagination = _pagination(args)
        sort = _sort(args, allowed={"id", "name"}, default="name")

        def query(repository: InventoryRepository) -> InventoryResponse:
            source = repository.get_active_source()
            page = repository.list_flavors(
                source, pagination.repository, sort.field, sort.descending
            )
            return InventoryResponse(
                [_normalize_flavor(row) for row in page.items],
                self._collection_meta(page) if pagination.include_meta else None,
            )

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
                repository = InventoryRepository(session, self._inventory_scope)
                return query(repository)
        except InventorySourceNotFound as error:
            raise ServiceUnavailable(
                "Configured inventory scope is unavailable."
            ) from error
        except InventoryResourceNotFound as error:
            raise NotFound(not_found_message) from error
        except SQLAlchemyError as error:
            self._logger.warning(
                "inventory_database_operation_failed",
                extra={"operation": operation, "error_type": type(error).__name__},
            )
            raise ServiceUnavailable("Inventory database is unavailable.") from error

    def _collection_meta(self, page: PageResult) -> dict[str, Any]:
        freshness = self._freshness(page.source)
        return {
            "page": page.page,
            "per_page": page.per_page,
            "total": page.total,
            "pages": ceil(page.total / page.per_page) if page.total else 0,
            "inventory_scope": page.source.scope_key,
            "last_successful_sync_at": _datetime_string(
                page.source.last_successful_sync_at
            ),
            "inventory_age_seconds": freshness["inventory_age_seconds"],
            "inventory_stale": freshness["inventory_stale"],
        }

    def _freshness(self, source: InventorySource) -> dict[str, int | bool | None]:
        last_success = source.last_successful_sync_at
        if last_success is None:
            return {"inventory_age_seconds": None, "inventory_stale": True}

        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=UTC)
        age_seconds = max(
            0, int((datetime.now(UTC) - last_success.astimezone(UTC)).total_seconds())
        )
        return {
            "inventory_age_seconds": age_seconds,
            "inventory_stale": age_seconds > self._max_age_seconds,
        }


def create_inventory_query_service(app: Flask) -> InventoryQueryService:
    """Create an inventory query service for a Flask app."""
    settings = cast(Settings, app.config["SETTINGS"])
    return InventoryQueryService(
        settings=settings,
        session_factory=get_inventory_session_factory(app),
        logger=app.logger,
    )


def _pagination(args: Mapping[str, str]) -> RequestPagination:
    page_supplied = "page" in args or "per_page" in args
    page = _positive_int(args.get("page", "1"), "page")
    per_page = _positive_int(args.get("per_page", str(DEFAULT_PER_PAGE)), "per_page")
    if per_page > MAX_PER_PAGE:
        raise BadRequest(f"per_page must be {MAX_PER_PAGE} or fewer.")
    return RequestPagination(Pagination(page=page, per_page=per_page), page_supplied)


def _positive_int(value: str | None, name: str) -> int:
    try:
        parsed = int(value or "")
    except ValueError as error:
        raise BadRequest(f"{name} must be a positive integer.") from error
    if parsed < 1:
        raise BadRequest(f"{name} must be a positive integer.")
    return parsed


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
        value = raw_value.strip()
        if not value:
            raise BadRequest(f"{key} filter must be non-empty.")
        filters[key] = value
    return filters


def _normalize_project(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row["id"]),
        "name": _string(row["name"]),
        "description": _optional_string(row["description"]),
        "enabled": _optional_bool(row["is_enabled"]),
        "domain_id": _optional_string(row["domain_id"]),
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
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)
