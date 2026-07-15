from __future__ import annotations

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


def test_servers_returns_all_185_active_servers_without_default_limit(
    inventory_app: Flask,
) -> None:
    response = inventory_app.test_client().get("/api/v1/servers")

    payload = response.get_json()
    assert response.status_code == 200
    assert len(payload["data"]) == 185
    assert payload["meta"] == {"count": 185}
    assert _scopes(payload["data"]) == {"appdev", "apptest"}


def test_page_and_per_page_do_not_limit_or_return_pagination_metadata(
    inventory_app: Flask,
) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?page=1&per_page=1")

    payload = response.get_json()
    assert response.status_code == 200
    assert len(payload["data"]) == 185
    assert payload["meta"] == {"count": 185}
    assert "page" not in payload["meta"]
    assert "per_page" not in payload["meta"]
    assert "pages" not in payload["meta"]


def test_server_response_includes_source_identity(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?scope=apptest")

    server = response.get_json()["data"][0]
    assert server["inventory_source"] == {
        "id": 2,
        "scope": "apptest",
        "project_id": "apptest-project",
        "project_name": "DF-APPTEST",
        "region_name": "RegionOne",
    }


def test_scope_filters_select_appdev_and_apptest(inventory_app: Flask) -> None:
    client = inventory_app.test_client()

    appdev = client.get("/api/v1/servers?scope=appdev").get_json()["data"]
    apptest = client.get("/api/v1/servers?scope=apptest").get_json()["data"]
    all_servers = client.get("/api/v1/servers").get_json()["data"]

    assert len(appdev) == 184
    assert len(apptest) == 1
    assert len(all_servers) == 185
    assert _scopes(appdev) == {"appdev"}
    assert _scopes(apptest) == {"apptest"}


def test_project_name_project_id_and_region_source_filters(
    inventory_app: Flask,
) -> None:
    client = inventory_app.test_client()

    by_name = client.get("/api/v1/servers?project_name=DF-APPDEV").get_json()["data"]
    by_id = client.get("/api/v1/servers?project_id=apptest-project").get_json()["data"]
    by_region = client.get("/api/v1/servers?region=RegionOne").get_json()["data"]

    assert len(by_name) == 184
    assert len(by_id) == 1
    assert len(by_region) == 185


def test_valid_source_filter_with_no_match_returns_empty_collection(
    inventory_app: Flask,
) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?scope=missing")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": [],
        "meta": {"count": 0},
    }


def test_invalid_source_filter_returns_400(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?scope=bad/scope")

    assert response.status_code == 400
    assert (
        response.get_json()["message"]
        == "scope filter contains unsupported characters."
    )


def test_soft_deleted_and_inactive_source_resources_are_excluded(
    inventory_app: Flask,
) -> None:
    response = inventory_app.test_client().get("/api/v1/servers")

    ids = {server["id"] for server in response.get_json()["data"]}
    assert "server-deleted" not in ids
    assert "inactive-server" not in ids


def test_single_tag_filter_matches_across_all_active_scopes(
    inventory_app: Flask,
) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?tag=production")

    servers = response.get_json()["data"]
    assert {
        (server["inventory_source"]["scope"], server["id"]) for server in servers
    } == {
        ("appdev", "server-1"),
        ("appdev", "server-2"),
        ("apptest", "server-1"),
    }


def test_multi_tag_filter_uses_and_matching_across_scopes(
    inventory_app: Flask,
) -> None:
    response = inventory_app.test_client().get("/api/v1/servers?tag=production&tag=web")

    servers = response.get_json()["data"]
    assert {
        (server["inventory_source"]["scope"], server["id"]) for server in servers
    } == {
        ("appdev", "server-1"),
        ("apptest", "server-1"),
    }


def test_scope_and_tag_filters_work_together(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get(
        "/api/v1/servers?scope=appdev&tag=production&tag=web"
    )

    servers = response.get_json()["data"]
    assert [
        (server["inventory_source"]["scope"], server["id"]) for server in servers
    ] == [("appdev", "server-1")]


def test_duplicate_tags_are_ignored(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get(
        "/api/v1/servers?tag=web&tag=web&tag=production"
    )

    assert response.status_code == 200
    assert response.get_json()["meta"] == {"count": 2}


def test_server_detail_unique_global_match(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers/server-2")

    assert response.status_code == 200
    assert response.get_json()["data"]["inventory_source"]["scope"] == "appdev"


def test_server_detail_duplicate_global_match_returns_409(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers/server-1")

    assert response.status_code == 409
    assert response.get_json() == {
        "status": "error",
        "message": (
            "Server ID matches multiple inventory sources; add a scope query parameter."
        ),
        "code": 409,
    }


def test_server_detail_duplicate_resolves_with_explicit_scope(
    inventory_app: Flask,
) -> None:
    client = inventory_app.test_client()

    appdev = client.get("/api/v1/servers/server-1?scope=appdev").get_json()["data"]
    apptest = client.get("/api/v1/servers/server-1?scope=apptest").get_json()["data"]

    assert appdev["name"] == "web01"
    assert apptest["name"] == "apptest-web"


def test_missing_server_returns_404(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers/missing")

    assert response.status_code == 404
    assert response.get_json() == {
        "status": "error",
        "message": "Inventory server was not found.",
        "code": 404,
    }


def test_addresses_join_on_source_and_server_id(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/servers/server-1?scope=apptest")

    addresses = response.get_json()["data"]["addresses"]
    assert addresses["private"][0]["addr"] == "10.1.0.5"
    assert "10.0.0.5" not in str(addresses)


def test_projects_networks_images_and_flavors_return_all_active_sources(
    inventory_app: Flask,
) -> None:
    client = inventory_app.test_client()

    projects = client.get("/api/v1/projects").get_json()["data"]
    networks = client.get("/api/v1/networks").get_json()["data"]
    images = client.get("/api/v1/images").get_json()["data"]
    flavors = client.get("/api/v1/flavors").get_json()["data"]

    assert _scopes(projects) == {"appdev", "apptest"}
    assert _scopes(networks) == {"appdev", "apptest"}
    assert _scopes(images) == {"appdev", "apptest"}
    assert _scopes(flavors) == {"appdev", "apptest"}
    assert len(images) == 2
    assert len(flavors) == 2


def test_inventory_sources_endpoint_returns_safe_fields(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/api/v1/inventory-sources")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["meta"] == {"count": 2}
    assert {source["scope"] for source in payload["data"]} == {"appdev", "apptest"}
    assert "auth_url" not in str(payload)


def test_health_reports_all_active_sources(inventory_app: Flask) -> None:
    response = inventory_app.test_client().get("/health")

    data = response.get_json()["data"]
    assert response.status_code == 200
    assert data["database"] == "healthy"
    assert data["active_inventory_sources"] == 2
    assert data["stale_inventory_sources"] == 0
    assert data["failed_inventory_sources"] == 0
    assert data["oldest_successful_sync_at"] is not None
    assert data["newest_successful_sync_at"] is not None


def test_health_remains_200_when_one_source_is_stale(inventory_engine: Engine) -> None:
    with inventory_engine.begin() as connection:
        connection.execute(
            update(models.inventory_sources)
            .where(models.inventory_sources.c.scope_key == "appdev")
            .values(last_successful_sync_at=datetime.now(UTC) - timedelta(hours=1))
        )
    app = make_inventory_app(inventory_engine)

    response = app.test_client().get("/health")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["stale_inventory_sources"] == 1
    assert data["stale_inventory_scopes"] == ["appdev"]


def test_health_returns_503_when_no_active_sources(inventory_engine: Engine) -> None:
    with inventory_engine.begin() as connection:
        connection.execute(update(models.inventory_sources).values(is_active=False))
    app = make_inventory_app(inventory_engine)

    response = app.test_client().get("/health")

    assert response.status_code == 503
    assert (
        response.get_json()["message"] == "No active inventory sources are available."
    )


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


def test_missing_inventory_scope_no_longer_fails_validation() -> None:
    settings = inventory_settings(inventory_scope=None)

    settings.validate_inventory()


def test_missing_mysql_setting_fails_configuration_validation() -> None:
    settings = inventory_settings(mysql_host=None)

    with pytest.raises(ConfigurationError, match="MYSQL_HOST"):
        settings.validate_inventory()


def test_get_routes_do_not_instantiate_openstack(
    inventory_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openstack(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("OpenStack client should not be built for GET routes")

    monkeypatch.setattr("app.routes.openstack.OpenStackClient", fail_openstack)

    client = inventory_app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/servers?scope=appdev").status_code == 200
    assert client.get("/api/v1/projects").status_code == 200
    assert client.get("/api/v1/networks").status_code == 200
    assert client.get("/api/v1/images").status_code == 200
    assert client.get("/api/v1/flavors").status_code == 200
    assert client.get("/api/v1/inventory-sources").status_code == 200


def test_legacy_inventory_scope_setting_does_not_restrict_results(
    inventory_engine: Engine,
) -> None:
    app = make_inventory_app(inventory_engine, legacy_scope="appdev")

    response = app.test_client().get("/api/v1/servers")

    payload = response.get_json()
    assert len(payload["data"]) == 185
    assert _scopes(payload["data"]) == {"appdev", "apptest"}


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
    assert len(statements) <= 3


def test_server_collection_query_has_no_limit_clause(
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

    response = app.test_client().get("/api/v1/servers")

    assert response.status_code == 200
    assert all("LIMIT" not in statement.upper() for statement in statements)


def _scopes(resources: list[dict[str, Any]]) -> set[str]:
    return {resource["inventory_source"]["scope"] for resource in resources}
