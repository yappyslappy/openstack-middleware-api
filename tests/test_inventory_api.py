from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import event, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app import create_app
from app.config import ConfigurationError
from app.database import models
from app.services.inventory_query import InventoryQueryService
from tests.helpers import inventory_settings, make_inventory_app


def test_appdev_cannot_see_apptest_resources(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers")

    assert response.status_code == 200
    names = {server["name"] for server in response.get_json()["data"]}
    assert "web01" in names
    assert "apptest-web" not in names


def test_apptest_cannot_see_appdev_resources(
    inventory_app_factory: Callable[[str], Flask],
) -> None:
    app = inventory_app_factory("apptest")

    response = app.test_client().get("/api/v1/servers")

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        {
            "id": "server-1",
            "name": "apptest-web",
            "status": "ACTIVE",
            "project_id": "project-1",
            "flavor": "flavor-1",
            "image": "image-1",
            "addresses": {
                "private": [
                    {
                        "addr": "10.1.0.5",
                        "version": 4,
                        "OS-EXT-IPS:type": "fixed",
                        "OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:00:00:01",
                    }
                ]
            },
            "tags": ["apptest"],
            "created_at": "2026-01-01T12:00:00Z",
            "updated_at": "2026-01-02T12:00:00Z",
        }
    ]


def test_soft_deleted_rows_are_excluded(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers")

    ids = {server["id"] for server in response.get_json()["data"]}
    assert "server-deleted" not in ids


def test_server_list_uses_database_not_openstack(
    inventory_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openstack(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("OpenStack client should not be built for GET routes")

    monkeypatch.setattr("app.routes.openstack.OpenStackClient", fail_openstack)

    response = inventory_app.test_client().get("/api/v1/servers")

    assert response.status_code == 200


def test_server_details_use_composite_source_scoping(
    inventory_app_factory: Callable[[str], Flask],
) -> None:
    appdev_response = (
        inventory_app_factory("appdev").test_client().get("/api/v1/servers/server-1")
    )
    apptest_response = (
        inventory_app_factory("apptest").test_client().get("/api/v1/servers/server-1")
    )

    assert appdev_response.get_json()["data"]["name"] == "web01"
    assert apptest_response.get_json()["data"]["name"] == "apptest-web"


def test_missing_server_returns_404(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers/missing")

    assert response.status_code == 404
    assert response.get_json() == {
        "status": "error",
        "message": "Inventory server was not found.",
        "code": 404,
    }


def test_one_tag_filter(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?tag=web")

    assert [server["id"] for server in response.get_json()["data"]] == ["server-1"]


def test_multiple_tag_filter_uses_and_matching(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?tag=production&tag=web")

    assert [server["id"] for server in response.get_json()["data"]] == ["server-1"]


def test_server_missing_one_requested_tag_is_excluded(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get(
        "/api/v1/servers?tag=production&tag=database"
    )

    assert response.get_json()["data"] == []


def test_duplicate_tags_are_ignored(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get(
        "/api/v1/servers?tag=web&tag=web&tag=production"
    )

    assert [server["id"] for server in response.get_json()["data"]] == ["server-1"]


def test_addresses_join_on_source_and_server_id(
    inventory_app_factory: Callable[[str], Flask],
) -> None:
    response = (
        inventory_app_factory("apptest").test_client().get("/api/v1/servers/server-1")
    )

    addresses = response.get_json()["data"]["addresses"]
    assert addresses["private"][0]["addr"] == "10.1.0.5"
    assert "10.0.0.5" not in str(addresses)


def test_projects_networks_images_and_flavors_endpoints(inventory_app: Flask) -> None:
    client = inventory_app.test_client()

    assert client.get("/api/v1/projects").get_json()["data"][0]["name"] == "demo"
    assert client.get("/api/v1/networks").get_json()["data"][0]["mtu"] == 1500
    image = client.get("/api/v1/images").get_json()["data"][0]
    assert image["size_bytes"] == 1024
    assert "min_disk_gb" not in image
    flavor = client.get("/api/v1/flavors").get_json()["data"][0]
    assert flavor["ram_mb"] == 2048
    assert "ram" not in flavor


def test_database_unavailable_returns_503() -> None:
    def broken_session_factory() -> Any:
        raise OperationalError("SELECT 1", {}, Exception("password=secret-password"))

    settings = inventory_settings()
    app = create_app(settings)
    app.extensions["inventory_query_service"] = InventoryQueryService(
        settings=settings,
        session_factory=broken_session_factory,
        logger=app.logger,
    )

    response = app.test_client().get("/health")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload == {
        "status": "error",
        "message": "Inventory database is unavailable.",
        "code": 503,
    }
    assert "secret-password" not in str(payload)


def test_missing_inventory_scope_fails_configuration_validation() -> None:
    settings = inventory_settings(inventory_scope=None)

    with pytest.raises(ConfigurationError, match="INVENTORY_SCOPE"):
        settings.validate_inventory()


def test_unknown_inventory_scope_returns_503(
    inventory_app_factory: Callable[[str], Flask],
) -> None:
    response = inventory_app_factory("unknown").test_client().get("/api/v1/servers")

    assert response.status_code == 503
    assert (
        response.get_json()["message"] == "Configured inventory scope is unavailable."
    )


def test_health_reports_sync_freshness(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/health")

    data = response.get_json()["data"]
    assert data["database"] == "healthy"
    assert data["last_successful_sync_at"] is not None
    assert data["inventory_age_seconds"] >= 0
    assert data["inventory_stale"] is False


def test_stale_inventory_is_reported_with_http_200(inventory_engine: Engine) -> None:
    with inventory_engine.begin() as connection:
        connection.execute(
            update(models.inventory_sources)
            .where(models.inventory_sources.c.scope_key == "appdev")
            .values(last_successful_sync_at=datetime.now(UTC) - timedelta(hours=1))
        )
    app = make_inventory_app(inventory_engine)

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json()["data"]["inventory_stale"] is True


def test_pagination_metadata_and_boundaries(inventory_app: Flask) -> None:
    client = inventory_app.test_client()

    response = client.get("/api/v1/servers?page=1&per_page=1")
    payload = response.get_json()

    assert response.status_code == 200
    assert len(payload["data"]) == 1
    assert payload["meta"]["total"] == 2
    assert payload["meta"]["pages"] == 2

    invalid_response = client.get("/api/v1/servers?page=0")
    assert invalid_response.status_code == 400
    too_large_response = client.get("/api/v1/servers?per_page=501")
    assert too_large_response.status_code == 400


def test_sort_field_allowlisting(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?sort=raw")

    assert response.status_code == 400
    assert response.get_json()["message"] == "Unsupported sort field."


def test_server_filters_are_allowlisted(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?status=ACTIVE")

    assert response.status_code == 200
    assert len(response.get_json()["data"]) == 2


def test_server_collection_avoids_n_plus_one_queries(
    inventory_engine: Engine,
) -> None:
    app = make_inventory_app(inventory_engine)
    statements: list[str] = []

    @event.listens_for(inventory_engine, "before_cursor_execute")
    def record_query(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    response = app.test_client().get("/api/v1/servers?tag=production")

    assert response.status_code == 200
    assert len(statements) <= 5
