from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app import create_app
from app.config import Settings
from app.services.openstack_client import OpenStackClient


class RecordingRouteService:
    def __init__(self) -> None:
        self.last_tag: str | None = None

    def list_projects(self) -> list[dict[str, Any]]:
        return []

    def list_servers(self, tag: str | None = None) -> list[dict[str, Any]]:
        self.last_tag = tag
        return [{"id": "server-1", "tags": [tag] if tag else []}]

    def get_server(self, server_id: str) -> dict[str, Any]:
        return {"id": server_id}

    def list_networks(self) -> list[dict[str, Any]]:
        return []

    def list_images(self) -> list[dict[str, Any]]:
        return []

    def list_flavors(self) -> list[dict[str, Any]]:
        return []


class NativeTagCompute:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def servers(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append(kwargs)
        return [
            SimpleNamespace(
                id="server-1",
                name="web01",
                status="ACTIVE",
                project_id="project-1",
                flavor={"name": "m1.small"},
                image={"name": "Ubuntu 24.04"},
                addresses={},
                tags=["production"],
                created_at="2026-01-01T12:00:00Z",
            )
        ]

    def get_server(self, server_id: str) -> None:
        return None

    def flavors(self) -> list[Any]:
        return []


class FallbackTagCompute(NativeTagCompute):
    def servers(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append(kwargs)
        if "tags" in kwargs:
            raise TypeError("servers() got an unexpected keyword argument 'tags'")
        return [
            SimpleNamespace(id="server-1", name="web01", tags=["production"]),
            SimpleNamespace(id="server-2", name="db01", tags=["database"]),
        ]


class FakeConnection:
    def __init__(self, compute: Any) -> None:
        self.compute = compute


def test_valid_tag_query_is_public_and_passed_to_service() -> None:
    app = create_app(Settings(api_key="test-key", testing=True))
    service = RecordingRouteService()
    app.extensions["openstack_service"] = service
    client = app.test_client()

    response = client.get("/api/v1/servers?tag=production")

    assert response.status_code == 200
    assert service.last_tag == "production"
    assert response.get_json()["data"] == [{"id": "server-1", "tags": ["production"]}]


def test_empty_tag_query_returns_400() -> None:
    app = create_app(Settings(api_key="test-key", testing=True))
    app.extensions["openstack_service"] = RecordingRouteService()
    client = app.test_client()

    response = client.get("/api/v1/servers?tag=")

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "message": "Server tag must be non-empty.",
        "code": 400,
    }


def test_oversized_tag_query_returns_400() -> None:
    app = create_app(Settings(api_key="test-key", testing=True))
    app.extensions["openstack_service"] = RecordingRouteService()
    client = app.test_client()

    response = client.get(f"/api/v1/servers?tag={'x' * 129}")

    assert response.status_code == 400
    assert response.get_json()["code"] == 400


def test_native_openstack_tag_filtering_is_used() -> None:
    compute = NativeTagCompute()
    service = OpenStackClient(
        Settings(testing=True), connection=FakeConnection(compute)
    )

    servers = service.list_servers(tag="production")

    assert servers[0]["id"] == "server-1"
    assert compute.calls == [{"details": True, "tags": "production"}]


def test_fallback_tag_filtering_is_used_when_native_filter_is_unavailable() -> None:
    compute = FallbackTagCompute()
    service = OpenStackClient(
        Settings(testing=True), connection=FakeConnection(compute)
    )

    servers = service.list_servers(tag="production")

    assert [server["id"] for server in servers] == ["server-1"]
    assert compute.calls == [
        {"details": True, "tags": "production"},
        {"details": True},
    ]
