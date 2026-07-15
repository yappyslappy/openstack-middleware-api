from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.database import models
from tests.helpers import make_inventory_app


@pytest.fixture
def inventory_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    models.metadata.create_all(engine)
    _seed_inventory(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def inventory_app(inventory_engine: Engine) -> Flask:
    return make_inventory_app(inventory_engine)


@pytest.fixture
def inventory_app_factory(inventory_engine: Engine) -> Callable[[str], Flask]:
    def factory(legacy_scope: str = "appdev") -> Flask:
        return make_inventory_app(inventory_engine, legacy_scope)

    return factory


def _seed_inventory(engine: Engine) -> None:
    sync_at = datetime.now(UTC)
    created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    updated_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)

    with engine.begin() as connection:
        connection.execute(
            models.inventory_sources.insert(),
            [
                _source(1, "appdev", sync_at),
                _source(2, "apptest", sync_at),
                _source(3, "inactive", sync_at, active=False),
            ],
        )
        connection.execute(
            models.projects.insert(),
            [
                _project(1, "project-1", "demo", created_at, updated_at),
                _project(1, "project-deleted", "deleted", created_at, updated_at, True),
                _project(2, "project-1", "apptest", created_at, updated_at),
                _project(3, "project-1", "inactive", created_at, updated_at),
            ],
        )
        bulk_servers = [
            _server(
                1,
                f"bulk-{number:03d}",
                f"bulk-{number:03d}",
                created_at,
                updated_at,
            )
            for number in range(1, 183)
        ]
        connection.execute(
            models.servers.insert(),
            [
                _server(
                    1,
                    "server-1",
                    "web01",
                    created_at,
                    updated_at,
                    addresses={"fallback": [{"addr": "10.0.0.99"}]},
                ),
                _server(1, "server-2", "api01", created_at, updated_at),
                *bulk_servers,
                _server(
                    1,
                    "server-deleted",
                    "old01",
                    created_at,
                    updated_at,
                    deleted=True,
                ),
                _server(2, "server-1", "apptest-web", created_at, updated_at),
                _server(3, "inactive-server", "inactive01", created_at, updated_at),
            ],
        )
        connection.execute(
            models.server_tags.insert(),
            [
                {
                    "inventory_source_id": 1,
                    "server_id": "server-1",
                    "tag": "production",
                },
                {"inventory_source_id": 1, "server_id": "server-1", "tag": "web"},
                {
                    "inventory_source_id": 1,
                    "server_id": "server-2",
                    "tag": "production",
                },
                {
                    "inventory_source_id": 2,
                    "server_id": "server-1",
                    "tag": "production",
                },
                {"inventory_source_id": 2, "server_id": "server-1", "tag": "web"},
                {"inventory_source_id": 2, "server_id": "server-1", "tag": "apptest"},
                {
                    "inventory_source_id": 3,
                    "server_id": "inactive-server",
                    "tag": "production",
                },
            ],
        )
        connection.execute(
            models.server_addresses.insert(),
            [
                _address(1, "server-1", "private", "10.0.0.5"),
                _address(1, "server-1", "public", "203.0.113.10", "floating"),
                _address(2, "server-1", "private", "10.1.0.5"),
                _address(3, "inactive-server", "private", "10.2.0.5"),
            ],
        )
        connection.execute(
            models.networks.insert(),
            [
                _network(1, "network-1", "private", created_at, updated_at),
                _network(1, "network-deleted", "old-net", created_at, updated_at, True),
                _network(2, "network-1", "apptest-net", created_at, updated_at),
                _network(3, "network-1", "inactive-net", created_at, updated_at),
            ],
        )
        connection.execute(
            models.images.insert(),
            [
                _image(1, "image-1", "Ubuntu 24.04", created_at, updated_at),
                _image(1, "image-deleted", "old-image", created_at, updated_at, True),
                _image(2, "image-1", "AppTest Image", created_at, updated_at),
                _image(3, "image-1", "Inactive Image", created_at, updated_at),
            ],
        )
        connection.execute(
            models.flavors.insert(),
            [
                _flavor(1, "flavor-1", "m1.small", created_at, updated_at),
                _flavor(
                    1, "flavor-deleted", "old-flavor", created_at, updated_at, True
                ),
                _flavor(2, "flavor-1", "apptest.small", created_at, updated_at),
                _flavor(3, "flavor-1", "inactive.small", created_at, updated_at),
            ],
        )


def _source(
    source_id: int,
    scope: str,
    sync_at: datetime,
    active: bool = True,
) -> dict[str, Any]:
    return {
        "id": source_id,
        "scope_key": scope,
        "openstack_project_id": f"{scope}-project",
        "openstack_project_name": f"DF-{scope.upper()}",
        "region_name": "RegionOne",
        "auth_url": "https://openstack.example/v3",
        "is_active": active,
        "last_successful_sync_at": sync_at,
        "last_failed_sync_at": None,
    }


def _project(
    source_id: int,
    project_id: str,
    name: str,
    created_at: datetime,
    updated_at: datetime,
    deleted: bool = False,
) -> dict[str, Any]:
    return _resource(
        source_id,
        project_id,
        name,
        created_at,
        updated_at,
        description=f"{name} project",
        is_enabled=True,
        domain_id="default",
        is_deleted=deleted,
    )


def _server(
    source_id: int,
    server_id: str,
    name: str,
    created_at: datetime,
    updated_at: datetime,
    deleted: bool = False,
    addresses: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _resource(
        source_id,
        server_id,
        name,
        created_at,
        updated_at,
        project_id=_project_id_for_source(source_id),
        status="ACTIVE",
        user_id="user-1",
        flavor_id="flavor-1",
        image_id="image-1",
        availability_zone="nova",
        compute_host="compute-1",
        vm_state="active",
        power_state="running",
        addresses=addresses or {},
        metadata_json={},
        is_deleted=deleted,
    )


def _address(
    source_id: int,
    server_id: str,
    network: str,
    address: str,
    address_type: str = "fixed",
) -> dict[str, Any]:
    return {
        "inventory_source_id": source_id,
        "server_id": server_id,
        "network_name": network,
        "address": address,
        "address_type": address_type,
        "version": 4,
        "mac_address": "fa:16:3e:00:00:01",
        "raw": {},
    }


def _network(
    source_id: int,
    network_id: str,
    name: str,
    created_at: datetime,
    updated_at: datetime,
    deleted: bool = False,
) -> dict[str, Any]:
    return _resource(
        source_id,
        network_id,
        name,
        created_at,
        updated_at,
        project_id=_project_id_for_source(source_id),
        status="ACTIVE",
        mtu=1500,
        admin_state_up=True,
        is_shared=False,
        is_router_external=False,
        provider_network_type="vxlan",
        provider_physical_network=None,
        provider_segmentation_id=1001,
        is_deleted=deleted,
    )


def _image(
    source_id: int,
    image_id: str,
    name: str,
    created_at: datetime,
    updated_at: datetime,
    deleted: bool = False,
) -> dict[str, Any]:
    return _resource(
        source_id,
        image_id,
        name,
        created_at,
        updated_at,
        status="active",
        visibility="public",
        container_format="bare",
        disk_format="qcow2",
        min_disk=10,
        min_ram=512,
        size_bytes=1024,
        checksum="abc123",
        is_deleted=deleted,
    )


def _flavor(
    source_id: int,
    flavor_id: str,
    name: str,
    created_at: datetime,
    updated_at: datetime,
    deleted: bool = False,
) -> dict[str, Any]:
    return _resource(
        source_id,
        flavor_id,
        name,
        created_at,
        updated_at,
        vcpus=1,
        ram_mb=2048,
        disk_gb=20,
        ephemeral_gb=0,
        swap_mb=0,
        is_public=True,
        is_deleted=deleted,
    )


def _resource(
    source_id: int,
    resource_id: str,
    name: str,
    created_at: datetime,
    updated_at: datetime,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inventory_source_id": source_id,
        "id": resource_id,
        "region_name": "RegionOne",
        "name": name,
        "project_id": extra.pop("project_id", None),
        "status": extra.pop("status", None),
        "raw": extra.pop("raw", {}),
        "first_seen_at": created_at,
        "last_seen_at": updated_at,
        "resource_created_at": created_at,
        "resource_updated_at": updated_at,
        "is_deleted": extra.pop("is_deleted", False),
        "deleted_at": None,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    data.update(extra)
    return data


def _project_id_for_source(source_id: int) -> str:
    project_ids = {
        1: "appdev-project",
        2: "apptest-project",
        3: "inactive-project",
    }
    return project_ids[source_id]
