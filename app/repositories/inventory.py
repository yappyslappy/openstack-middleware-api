from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, text, tuple_
from sqlalchemy.orm import Session

from app.database import models


class InventoryResourceNotFound(Exception):
    """Raised when a requested resource does not exist."""


class InventoryResourceAmbiguous(Exception):
    """Raised when a requested resource ID exists in multiple active sources."""


@dataclass(frozen=True, slots=True)
class InventorySource:
    """Safe active inventory source metadata."""

    id: int
    scope: str
    openstack_project_id: str | None
    openstack_project_name: str | None
    region_name: str | None
    last_successful_sync_at: datetime | None
    last_failed_sync_at: datetime | None


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Unpaginated inventory rows plus total count."""

    items: list[dict[str, Any]]
    total: int


class InventoryRepository:
    """SQLAlchemy Core queries for sync-owned inventory tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def check_database(self) -> None:
        """Run a lightweight database connectivity check."""
        self._session.execute(text("SELECT 1")).scalar_one()

    def list_inventory_sources(
        self, source_filters: Mapping[str, str] | None = None
    ) -> CollectionResult:
        """Return safe metadata for all active inventory sources."""
        source = models.inventory_sources
        statement = (
            select(
                source.c.id,
                source.c.scope_key,
                source.c.openstack_project_id,
                source.c.openstack_project_name,
                source.c.region_name,
                source.c.last_successful_sync_at,
                source.c.last_failed_sync_at,
            )
            .where(
                source.c.is_active.is_(True),
                *_source_filter_conditions(source, source_filters or {}),
            )
            .order_by(source.c.scope_key, source.c.id)
        )
        rows = [dict(row) for row in self._session.execute(statement).mappings().all()]
        return CollectionResult(items=rows, total=len(rows))

    def list_projects(
        self,
        source_filters: Mapping[str, str],
        sort_field: str,
        sort_descending: bool,
    ) -> CollectionResult:
        table = models.projects
        return self._list_resource(
            table=table,
            source_filters=source_filters,
            columns=[
                table.c.inventory_source_id,
                table.c.id,
                table.c.name,
                table.c.description,
                table.c.is_enabled,
                table.c.domain_id,
                table.c.resource_created_at,
                table.c.resource_updated_at,
            ],
            sort_field=sort_field,
            sort_descending=sort_descending,
            sort_columns={"id": table.c.id, "name": table.c.name},
        )

    def list_servers(
        self,
        source_filters: Mapping[str, str],
        resource_filters: Mapping[str, str],
        tags: Sequence[str],
        sort_field: str,
        sort_descending: bool,
    ) -> CollectionResult:
        source = models.inventory_sources
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
            *_source_columns(source),
        ]
        statement = select(*columns).select_from(
            table.join(source, source.c.id == table.c.inventory_source_id)
        )
        statement = statement.where(
            source.c.is_active.is_(True),
            table.c.is_deleted.is_(False),
            *_source_filter_conditions(source, source_filters),
        )

        for filter_name, filter_value in resource_filters.items():
            statement = statement.where(getattr(table.c, filter_name) == filter_value)

        if tags:
            tag_table = models.server_tags
            matching_servers = (
                select(table.c.inventory_source_id, table.c.id)
                .select_from(
                    table.join(source, source.c.id == table.c.inventory_source_id).join(
                        tag_table,
                        and_(
                            tag_table.c.inventory_source_id
                            == table.c.inventory_source_id,
                            tag_table.c.server_id == table.c.id,
                        ),
                    )
                )
                .where(
                    source.c.is_active.is_(True),
                    table.c.is_deleted.is_(False),
                    tag_table.c.tag.in_(list(tags)),
                    *_source_filter_conditions(source, source_filters),
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

        statement = statement.order_by(source.c.scope_key, sort_column, table.c.id)
        rows = [dict(row) for row in self._session.execute(statement).mappings().all()]
        items = self._hydrate_servers(rows)
        return CollectionResult(items=items, total=len(items))

    def get_server(
        self,
        server_id: str,
        source_filters: Mapping[str, str],
    ) -> dict[str, Any]:
        """Return one active server, or raise on missing/ambiguous matches."""
        source = models.inventory_sources
        table = models.servers
        rows = (
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
                    *_source_columns(source),
                )
                .select_from(
                    table.join(source, source.c.id == table.c.inventory_source_id)
                )
                .where(
                    source.c.is_active.is_(True),
                    table.c.id == server_id,
                    table.c.is_deleted.is_(False),
                    *_source_filter_conditions(source, source_filters),
                )
                .order_by(source.c.scope_key, table.c.id)
            )
            .mappings()
            .all()
        )
        if not rows:
            raise InventoryResourceNotFound
        if len(rows) > 1:
            raise InventoryResourceAmbiguous
        return self._hydrate_servers([dict(rows[0])])[0]

    def list_networks(
        self,
        source_filters: Mapping[str, str],
        sort_field: str,
        sort_descending: bool,
    ) -> CollectionResult:
        table = models.networks
        return self._list_resource(
            table=table,
            source_filters=source_filters,
            columns=[
                table.c.inventory_source_id,
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
        source_filters: Mapping[str, str],
        sort_field: str,
        sort_descending: bool,
    ) -> CollectionResult:
        table = models.images
        return self._list_resource(
            table=table,
            source_filters=source_filters,
            columns=[
                table.c.inventory_source_id,
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
        source_filters: Mapping[str, str],
        sort_field: str,
        sort_descending: bool,
    ) -> CollectionResult:
        table = models.flavors
        return self._list_resource(
            table=table,
            source_filters=source_filters,
            columns=[
                table.c.inventory_source_id,
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
            sort_field=sort_field,
            sort_descending=sort_descending,
            sort_columns={"id": table.c.id, "name": table.c.name},
        )

    def _list_resource(
        self,
        *,
        table: Any,
        source_filters: Mapping[str, str],
        columns: Sequence[Any],
        sort_field: str,
        sort_descending: bool,
        sort_columns: Mapping[str, Any],
    ) -> CollectionResult:
        source = models.inventory_sources
        sort_column: Any = sort_columns[sort_field]
        if sort_descending:
            sort_column = sort_column.desc()

        statement = (
            select(*columns, *_source_columns(source))
            .select_from(table.join(source, source.c.id == table.c.inventory_source_id))
            .where(
                source.c.is_active.is_(True),
                table.c.is_deleted.is_(False),
                *_source_filter_conditions(source, source_filters),
            )
            .order_by(source.c.scope_key, sort_column, table.c.id)
        )
        rows = [dict(row) for row in self._session.execute(statement).mappings().all()]
        return CollectionResult(items=rows, total=len(rows))

    def _hydrate_servers(
        self, server_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not server_rows:
            return []

        server_keys = _server_keys(server_rows)
        tags_by_server = self._tags_by_server(server_keys)
        addresses_by_server = self._addresses_by_server(server_keys)
        for row in server_rows:
            key = (int(row["inventory_source_id"]), str(row["id"]))
            row["tags"] = tags_by_server.get(key, [])
            row["normalized_addresses"] = addresses_by_server.get(key, {})
        return server_rows

    def _tags_by_server(
        self, server_keys: Sequence[tuple[int, str]]
    ) -> dict[tuple[int, str], list[str]]:
        tag_table = models.server_tags
        rows = (
            self._session.execute(
                select(
                    tag_table.c.inventory_source_id,
                    tag_table.c.server_id,
                    tag_table.c.tag,
                )
                .where(
                    tuple_(tag_table.c.inventory_source_id, tag_table.c.server_id).in_(
                        list(server_keys)
                    )
                )
                .order_by(
                    tag_table.c.inventory_source_id,
                    tag_table.c.server_id,
                    tag_table.c.tag,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[tuple[int, str], list[str]] = {key: [] for key in server_keys}
        for row in rows:
            key = (int(row["inventory_source_id"]), str(row["server_id"]))
            grouped[key].append(str(row["tag"]))
        return grouped

    def _addresses_by_server(
        self, server_keys: Sequence[tuple[int, str]]
    ) -> dict[tuple[int, str], dict[str, list[dict[str, Any]]]]:
        address_table = models.server_addresses
        rows = (
            self._session.execute(
                select(
                    address_table.c.inventory_source_id,
                    address_table.c.server_id,
                    address_table.c.network_name,
                    address_table.c.address,
                    address_table.c.address_type,
                    address_table.c.version,
                    address_table.c.mac_address,
                )
                .where(
                    tuple_(
                        address_table.c.inventory_source_id,
                        address_table.c.server_id,
                    ).in_(list(server_keys))
                )
                .order_by(
                    address_table.c.inventory_source_id,
                    address_table.c.server_id,
                    address_table.c.network_name,
                    address_table.c.address,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[tuple[int, str], dict[str, list[dict[str, Any]]]] = {}
        for row in rows:
            key = (int(row["inventory_source_id"]), str(row["server_id"]))
            network_name = str(row["network_name"])
            grouped.setdefault(key, {}).setdefault(network_name, []).append(
                _address_payload(dict(row))
            )
        return grouped


def _source_columns(source: Any) -> list[Any]:
    return [
        source.c.id.label("source_id"),
        source.c.scope_key.label("source_scope"),
        source.c.openstack_project_id.label("source_openstack_project_id"),
        source.c.openstack_project_name.label("source_openstack_project_name"),
        source.c.region_name.label("source_region_name"),
        source.c.last_successful_sync_at.label("source_last_successful_sync_at"),
        source.c.last_failed_sync_at.label("source_last_failed_sync_at"),
    ]


def _source_filter_conditions(source: Any, filters: Mapping[str, str]) -> list[Any]:
    filter_columns = {
        "scope": source.c.scope_key,
        "project_id": source.c.openstack_project_id,
        "project_name": source.c.openstack_project_name,
        "region": source.c.region_name,
    }
    return [filter_columns[key] == value for key, value in filters.items()]


def _server_keys(rows: Sequence[Mapping[str, Any]]) -> list[tuple[int, str]]:
    keys: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        key = (int(row["inventory_source_id"]), str(row["id"]))
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _address_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"addr": row["address"]}
    if row["version"] is not None:
        payload["version"] = row["version"]
    if row["address_type"] is not None:
        payload["OS-EXT-IPS:type"] = row["address_type"]
    if row["mac_address"] is not None:
        payload["OS-EXT-IPS-MAC:mac_addr"] = row["mac_address"]
    return payload
