from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from flask.testing import FlaskClient

from app import create_app
from app.config import Settings
from app.services.openstack_client import OpenStackClient


class RecordingRouteService:
    def __init__(self) -> None:
        self.last_tags: list[str] | None = None

    def list_projects(self) -> list[dict[str, Any]]:
        return []

    def list_servers(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        self.last_tags = list(tags or [])
        return [{"id": "server-1", "tags": self.last_tags}]

    def get_server(self, server_id: str) -> dict[str, Any]:
        return {"id": server_id}

    def list_networks(self) -> list[dict[str, Any]]:
        return []

    def list_images(self) -> list[dict[str, Any]]:
        return []

    def list_flavors(self) -> list[dict[str, Any]]:
        return []


class NativeTagCompute:
    def __init__(self, servers: list[SimpleNamespace] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._servers = servers or [_server("server-1", ["production", "web", "linux"])]

    def servers(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append(kwargs)
        return self._servers

    def get_server(self, server_id: str) -> None:
        return None

    def flavors(self) -> list[Any]:
        return []


class FallbackTagCompute(NativeTagCompute):
    def servers(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append(kwargs)
        if "tags" in kwargs:
            raise TypeError("servers() got an unexpected keyword argument 'tags'")
        return self._servers


class FakeConnection:
    def __init__(self, compute: Any) -> None:
        self.compute = compute


def _server(server_id: str, tags: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=server_id,
        name=server_id,
        status="ACTIVE",
        project_id="project-1",
        flavor={"name": "m1.small"},
        image={"name": "Ubuntu 24.04"},
        addresses={},
        tags=tags,
        created_at="2026-01-01T12:00:00Z",
    )


def _client_with_service(service: Any) -> FlaskClient:
    app = create_app(Settings(api_key="test-key", testing=True))
    app.extensions["openstack_service"] = service
    return app.test_client()


def _openstack_service(compute: Any) -> OpenStackClient:
    return OpenStackClient(Settings(testing=True), connection=FakeConnection(compute))


def test_no_tag_query_is_public_and_passes_empty_tags_to_service() -> None:
    service = RecordingRouteService()
    client = _client_with_service(service)

    response = client.get("/api/v1/servers")

    assert response.status_code == 200
    assert service.last_tags == []
    assert response.get_json()["data"] == [{"id": "server-1", "tags": []}]


def test_valid_single_tag_query_is_public_and_passed_to_service() -> None:
    service = RecordingRouteService()
    client = _client_with_service(service)

    response = client.get("/api/v1/servers?tag=production")

    assert response.status_code == 200
    assert service.last_tags == ["production"]
    assert response.get_json()["data"] == [{"id": "server-1", "tags": ["production"]}]


def test_duplicate_and_whitespace_tags_are_normalized_for_service() -> None:
    service = RecordingRouteService()
    client = _client_with_service(service)

    response = client.get("/api/v1/servers?tag=%20web%20&tag=web&tag=production")

    assert response.status_code == 200
    assert service.last_tags == ["web", "production"]


def test_empty_tag_query_returns_400() -> None:
    client = _client_with_service(RecordingRouteService())

    response = client.get("/api/v1/servers?tag=")

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "message": "Server tag must be non-empty.",
        "code": 400,
    }


def test_whitespace_only_tag_query_returns_400() -> None:
    client = _client_with_service(RecordingRouteService())

    response = client.get("/api/v1/servers?tag=%20%20%20")

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "message": "Server tag must be non-empty.",
        "code": 400,
    }


def test_oversized_tag_query_returns_400() -> None:
    client = _client_with_service(RecordingRouteService())

    response = client.get(f"/api/v1/servers?tag={'x' * 129}")

    assert response.status_code == 400
    assert response.get_json()["code"] == 400


def test_service_returns_all_visible_servers_when_tags_are_empty_or_none() -> None:
    compute = NativeTagCompute()
    service = _openstack_service(compute)

    none_filtered_servers = service.list_servers()
    empty_filtered_servers = service.list_servers(tags=[])

    assert [server["id"] for server in none_filtered_servers] == ["server-1"]
    assert [server["id"] for server in empty_filtered_servers] == ["server-1"]
    assert compute.calls == [{"details": True}, {"details": True}]


def test_service_filters_two_matching_tags() -> None:
    compute = NativeTagCompute(
        [
            _server("server-1", ["production", "web", "linux"]),
            _server("server-2", ["production", "database"]),
        ]
    )
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web"])

    assert [server["id"] for server in servers] == ["server-1"]


def test_service_filters_three_matching_tags() -> None:
    compute = NativeTagCompute(
        [
            _server("server-1", ["production", "web", "linux"]),
            _server("server-2", ["production", "web"]),
        ]
    )
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web", "linux"])

    assert [server["id"] for server in servers] == ["server-1"]


def test_service_excludes_servers_missing_one_requested_tag() -> None:
    compute = NativeTagCompute(
        [
            _server("server-1", ["production", "database"]),
            _server("server-2", ["web", "linux"]),
        ]
    )
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web"])

    assert servers == []


def test_service_uses_and_matching_instead_of_or_matching() -> None:
    compute = NativeTagCompute(
        [
            _server("server-1", ["production"]),
            _server("server-2", ["web"]),
            _server("server-3", ["production", "web"]),
        ]
    )
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web"])

    assert [server["id"] for server in servers] == ["server-3"]


def test_service_normalizes_none_tags_to_empty_list() -> None:
    compute = NativeTagCompute([_server("server-1", None)])
    service = _openstack_service(compute)

    servers = service.list_servers()

    assert servers[0]["tags"] == []


def test_service_matches_tuple_tags() -> None:
    compute = NativeTagCompute([_server("server-1", ("production", "web"))])
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web"])

    assert [server["id"] for server in servers] == ["server-1"]
    assert servers[0]["tags"] == ["production", "web"]


def test_service_deduplicates_tags_without_mutating_input() -> None:
    compute = NativeTagCompute()
    service = _openstack_service(compute)
    tags = ["web", "web", "production"]

    service.list_servers(tags=tags)

    assert tags == ["web", "web", "production"]
    assert compute.calls == [{"details": True, "tags": "web,production"}]


def test_native_openstack_multi_tag_filtering_uses_comma_separated_tags() -> None:
    compute = NativeTagCompute()
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web"])

    assert servers[0]["id"] == "server-1"
    assert compute.calls == [{"details": True, "tags": "production,web"}]


def test_fallback_tag_filtering_is_used_when_native_filter_is_unavailable() -> None:
    compute = FallbackTagCompute(
        [
            _server("server-1", ["production", "web"]),
            _server("server-2", ["production"]),
            _server("server-3", ["database", "web"]),
        ]
    )
    service = _openstack_service(compute)

    servers = service.list_servers(tags=["production", "web"])

    assert [server["id"] for server in servers] == ["server-1"]
    assert compute.calls == [
        {"details": True, "tags": "production,web"},
        {"details": True},
    ]
