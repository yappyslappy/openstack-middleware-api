from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.database import models


class InventorySourceNotFound(Exception):
    """Raised when the configured active inventory source does not exist."""


class InventoryResourceNotFound(Exception):
    """Raised when a scoped resource does not exist."""


@dataclass(frozen=True, slots=True)
class InventorySource:
    """Active inventory source selected by deployment scope."""

    id: int
    scope_key: str
    last_successful_sync_at: datetime | None
    last_failed_sync_at: datetime | None


@dataclass(frozen=True, slots=True)
class Pagination:
    """Repository pagination options."""

    page: int
    per_page: int


@dataclass(frozen=True, slots=True)
class PageResult:
    """A page of inventory rows plus count/source metadata."""

    items: list[dict[str, Any]]
    total: int
    page: int
    per_page: int
    source: InventorySource


class InventoryRepository:
    """SQLAlchemy Core queries for sync-owned inventory tables."""

    def __init__(self, session: Session, inventory_scope: str) -> None:
        self._session = session
        self._inventory_scope = inventory_scope

    def check_database(self) -> None:
        """Run a lightweight database connectivity check."""
        self._session.execute(text("SELECT 1")).scalar_one()

    def get_active_source(self) -> InventorySource:
        """Return the active inventory source for the configured scope."""
        source = models.inventory_sources
        row = (
            self._session.execute(
                select(
                    source.c.id,
                    source.c.scope_key,
                    source.c.last_successful_sync_at,
                    source.c.last_failed_sync_at,
                ).where(
                    source.c.scope_key == self._inventory_scope,
                    source.c.is_active.is_(True),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise InventorySourceNotFound
        return InventorySource(
            id=int(row["id"]),
            scope_key=str(row["scope_key"]),
            last_successful_sync_at=row["last_successful_sync_at"],
            last_failed_sync_at=row["last_failed_sync_at"],
        )

    def list_projects(
        self,
        source: InventorySource,
        pagination: Pagination,
        sort_field: str,
        sort_descending: bool,
    ) -> PageResult:
        table = models.projects
        return self._list_resource(
            table=table,
            source=source,
            columns=[
                table.c.id,
                table.c.name,
                table.c.description,
                table.c.is_enabled,
                table.c.domain_id,
                table.c.resource_created_at,
                table.c.resource_updated_at,
            ],
            pagination=pagination,
            sort_field=sort_field,
            sort_descending=sort_descending,
            sort_columns={"id": table.c.id, "name": table.c.name},
        )

    def list_servers(
        self,
        source: InventorySource,
        pagination: Pagination,
        filters: Mapping[str, str],
        tags: Sequence[str],
        sort_field: str,
        sort_descending: bool,
    ) -> PageResult:
        table = models.servers
        columns = [
            table.c.inventory_source_id,
            table.c.id,
            table.c.name,
            table.c.status,
            table.c.project_id,
            table.c.flavor_id,
            table.c.image_id,
            table.c.addresses,
            table.c.resource_created_at,
            table.c.resource_updated_at,
        ]
        statement = select(*columns).where(
            table.c.inventory_source_id == source.id,
            table.c.is_deleted.is_(False),
        )

        for filter_name, filter_value in filters.items():
            statement = statement.where(getattr(table.c, filter_name) == filter_value)

        if tags:
            tag_table = models.server_tags
            matching_servers = (
                select(table.c.inventory_source_id, table.c.id)
                .join(
                    tag_table,
                    and_(
                        tag_table.c.inventory_source_id == table.c.inventory_source_id,
                        tag_table.c.server_id == table.c.id,
                    ),
                )
                .where(
                    table.c.inventory_source_id == source.id,
                    table.c.is_deleted.is_(False),
                    tag_table.c.tag.in_(list(tags)),
                )
                .group_by(table.c.inventory_source_id, table.c.id)
                .having(func.count(func.distinct(tag_table.c.tag)) == len(tags))
                .subquery()
            )
            statement = statement.join(
                matching_servers,
                and_(
                    matching_servers.c.inventory_source_id
                    == table.c.inventory_source_id,
                    matching_servers.c.id == table.c.id,
                ),
            )

        sort_columns = {
            "id": table.c.id,
            "name": table.c.name,
            "status": table.c.status,
            "project_id": table.c.project_id,
            "availability_zone": table.c.availability_zone,
            "compute_host": table.c.compute_host,
            "power_state": table.c.power_state,
            "vm_state": table.c.vm_state,
        }
        sort_column: Any = sort_columns[sort_field]
        if sort_descending:
            sort_column = sort_column.desc()

        statement = statement.order_by(sort_column, table.c.id)
        rows, total = self._paginate(statement, pagination)
        return PageResult(
            items=self._hydrate_servers(source.id, rows),
            total=total,
            page=pagination.page,
            per_page=pagination.per_page,
            source=source,
        )

    def get_server(self, source: InventorySource, server_id: str) -> dict[str, Any]:
        table = models.servers
        row = (
            self._session.execute(
                select(
                    table.c.inventory_source_id,
                    table.c.id,
                    table.c.name,
                    table.c.status,
                    table.c.project_id,
                    table.c.flavor_id,
                    table.c.image_id,
                    table.c.addresses,
                    table.c.resource_created_at,
                    table.c.resource_updated_at,
                ).where(
                    table.c.inventory_source_id == source.id,
                    table.c.id == server_id,
                    table.c.is_deleted.is_(False),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise InventoryResourceNotFound
        return self._hydrate_servers(source.id, [dict(row)])[0]

    def list_networks(
        self,
        source: InventorySource,
        pagination: Pagination,
        sort_field: str,
        sort_descending: bool,
    ) -> PageResult:
        table = models.networks
        return self._list_resource(
            table=table,
            source=source,
            columns=[
                table.c.id,
                table.c.name,
                table.c.project_id,
                table.c.status,
                table.c.mtu,
                table.c.admin_state_up,
                table.c.is_shared,
                table.c.is_router_external,
                table.c.provider_network_type,
                table.c.provider_physical_network,
                table.c.provider_segmentation_id,
                table.c.resource_created_at,
                table.c.resource_updated_at,
            ],
            pagination=pagination,
            sort_field=sort_field,
            sort_descending=sort_descending,
            sort_columns={
                "id": table.c.id,
                "name": table.c.name,
                "status": table.c.status,
            },
        )

    def list_images(
        self,
        source: InventorySource,
        pagination: Pagination,
        sort_field: str,
        sort_descending: bool,
    ) -> PageResult:
        table = models.images
        return self._list_resource(
            table=table,
            source=source,
            columns=[
                table.c.id,
                table.c.name,
                table.c.status,
                table.c.visibility,
                table.c.container_format,
                table.c.disk_format,
                table.c.min_disk,
                table.c.min_ram,
                table.c.size_bytes,
                table.c.checksum,
                table.c.resource_created_at,
                table.c.resource_updated_at,
            ],
            pagination=pagination,
            sort_field=sort_field,
            sort_descending=sort_descending,
            sort_columns={
                "id": table.c.id,
                "name": table.c.name,
                "status": table.c.status,
            },
        )

    def list_flavors(
        self,
        source: InventorySource,
        pagination: Pagination,
        sort_field: str,
        sort_descending: bool,
    ) -> PageResult:
        table = models.flavors
        return self._list_resource(
            table=table,
            source=source,
            columns=[
                table.c.id,
                table.c.name,
                table.c.vcpus,
                table.c.ram_mb,
                table.c.disk_gb,
                table.c.ephemeral_gb,
                table.c.swap_mb,
                table.c.is_public,
                table.c.resource_created_at,
                table.c.resource_updated_at,
            ],
            pagination=pagination,
            sort_field=sort_field,
            sort_descending=sort_descending,
            sort_columns={"id": table.c.id, "name": table.c.name},
        )

    def _list_resource(
        self,
        *,
        table: Any,
        source: InventorySource,
        columns: Sequence[Any],
        pagination: Pagination,
        sort_field: str,
        sort_descending: bool,
        sort_columns: Mapping[str, Any],
    ) -> PageResult:
        sort_column = sort_columns[sort_field]
        if sort_descending:
            sort_column = sort_column.desc()

        statement = (
            select(*columns)
            .where(
                table.c.inventory_source_id == source.id,
                table.c.is_deleted.is_(False),
            )
            .order_by(sort_column, table.c.id)
        )
        rows, total = self._paginate(statement, pagination)
        return PageResult(
            items=rows,
            total=total,
            page=pagination.page,
            per_page=pagination.per_page,
            source=source,
        )

    def _hydrate_servers(
        self, source_id: int, server_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not server_rows:
            return []

        server_ids = [str(row["id"]) for row in server_rows]
        tags_by_server = self._tags_by_server(source_id, server_ids)
        addresses_by_server = self._addresses_by_server(source_id, server_ids)
        for row in server_rows:
            server_id = str(row["id"])
            row["tags"] = tags_by_server.get(server_id, [])
            row["normalized_addresses"] = addresses_by_server.get(server_id, {})
        return server_rows

    def _tags_by_server(
        self, source_id: int, server_ids: Sequence[str]
    ) -> dict[str, list[str]]:
        tag_table = models.server_tags
        rows = (
            self._session.execute(
                select(tag_table.c.server_id, tag_table.c.tag)
                .where(
                    tag_table.c.inventory_source_id == source_id,
                    tag_table.c.server_id.in_(list(server_ids)),
                )
                .order_by(tag_table.c.server_id, tag_table.c.tag)
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[str]] = {server_id: [] for server_id in server_ids}
        for row in rows:
            grouped[str(row["server_id"])].append(str(row["tag"]))
        return grouped

    def _addresses_by_server(
        self, source_id: int, server_ids: Sequence[str]
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        address_table = models.server_addresses
        rows = (
            self._session.execute(
                select(
                    address_table.c.server_id,
                    address_table.c.network_name,
                    address_table.c.address,
                    address_table.c.address_type,
                    address_table.c.version,
                    address_table.c.mac_address,
                )
                .where(
                    address_table.c.inventory_source_id == source_id,
                    address_table.c.server_id.in_(list(server_ids)),
                )
                .order_by(
                    address_table.c.server_id,
                    address_table.c.network_name,
                    address_table.c.address,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for row in rows:
            server_id = str(row["server_id"])
            network_name = str(row["network_name"])
            grouped.setdefault(server_id, {}).setdefault(network_name, []).append(
                _address_payload(dict(row))
            )
        return grouped

    def _paginate(
        self, statement: Any, pagination: Pagination
    ) -> tuple[list[dict[str, Any]], int]:
        total = self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        rows = (
            self._session.execute(
                statement.limit(pagination.per_page).offset(
                    (pagination.page - 1) * pagination.per_page
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows], int(total or 0)


def _address_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"addr": row["address"]}
    if row["version"] is not None:
        payload["version"] = row["version"]
    if row["address_type"] is not None:
        payload["OS-EXT-IPS:type"] = row["address_type"]
    if row["mac_address"] is not None:
        payload["OS-EXT-IPS-MAC:mac_addr"] = row["mac_address"]
    return payload
