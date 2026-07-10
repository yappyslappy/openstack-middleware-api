from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app import create_app
from app.config import Settings
from app.errors.handlers import NotFound
from app.services.openstack_client import OpenStackClient


class FakeIdentity:
    def projects(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id="project-1",
                name="demo",
                description="Demo project",
                is_enabled=True,
                domain_id="default",
            )
        ]


class FakeCompute:
    def __init__(self) -> None:
        self.servers_calls: list[dict[str, Any]] = []

    def servers(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.servers_calls.append(kwargs)
        return [
            SimpleNamespace(
                id="server-1",
                name="web01",
                status="ACTIVE",
                project_id="project-1",
                flavor={"original_name": "m1.small"},
                image={"name": "Ubuntu 24.04"},
                addresses={"private": []},
                tags=["production", "web"],
                created_at="2026-01-01T12:00:00Z",
            )
        ]

    def get_server(self, server_id: str) -> SimpleNamespace | None:
        if server_id != "server-1":
            return None
        return self.servers()[0]

    def flavors(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "flavor-1",
                "name": "m1.small",
                "vcpus": 1,
                "ram": 2048,
                "disk": 20,
                "is_public": True,
            }
        ]


class FakeNetwork:
    def networks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "network-1",
                "name": "private",
                "status": "ACTIVE",
                "project_id": "project-1",
                "is_shared": False,
                "router:external": False,
                "subnets": ["subnet-1"],
            }
        ]


class FakeImage:
    def images(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "image-1",
                "name": "Ubuntu 24.04",
                "status": "active",
                "visibility": "public",
                "size": 1024,
                "min_disk": 10,
                "min_ram": 512,
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]


class FakeConnection:
    def __init__(self) -> None:
        self.identity = FakeIdentity()
        self.compute = FakeCompute()
        self.network = FakeNetwork()
        self.image = FakeImage()


class FakeRouteService:
    def list_projects(self) -> list[dict[str, str]]:
        return [{"id": "project-1", "name": "demo"}]

    def list_servers(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        return [{"id": "server-1", "name": "web01", "tags": tags or []}]

    def get_server(self, server_id: str) -> dict[str, str]:
        if server_id != "server-1":
            raise NotFound("OpenStack server was not found.")
        return {"id": "server-1", "name": "web01"}

    def list_networks(self) -> list[dict[str, str]]:
        return [{"id": "network-1", "name": "private"}]

    def list_images(self) -> list[dict[str, str]]:
        return [{"id": "image-1", "name": "Ubuntu 24.04"}]

    def list_flavors(self) -> list[dict[str, str]]:
        return [{"id": "flavor-1", "name": "m1.small"}]


def test_openstack_service_normalizes_resources() -> None:
    service = OpenStackClient(Settings(testing=True), connection=FakeConnection())

    assert service.list_projects()[0]["name"] == "demo"
    assert service.list_servers()[0] == {
        "id": "server-1",
        "name": "web01",
        "status": "ACTIVE",
        "project_id": "project-1",
        "flavor": "m1.small",
        "image": "Ubuntu 24.04",
        "addresses": {"private": []},
        "tags": ["production", "web"],
        "created_at": "2026-01-01T12:00:00Z",
    }
    assert service.get_server("server-1")["id"] == "server-1"
    assert service.list_networks()[0]["id"] == "network-1"
    assert service.list_images()[0]["id"] == "image-1"
    assert service.list_flavors()[0]["id"] == "flavor-1"


def test_get_server_not_found_is_standardized() -> None:
    service = OpenStackClient(Settings(testing=True), connection=FakeConnection())

    try:
        service.get_server("missing")
    except NotFound as error:
        assert error.status_code == 404
        assert error.message == "OpenStack server was not found."
    else:
        raise AssertionError("expected NotFound")


def test_api_routes_use_standard_success_envelope() -> None:
    app = create_app(Settings(api_key="test-key", testing=True))
    app.extensions["openstack_service"] = FakeRouteService()
    client = app.test_client()

    assert client.get("/api/v1/projects").get_json() == {
        "status": "success",
        "data": [{"id": "project-1", "name": "demo"}],
    }
    assert client.get("/api/v1/servers/server-1").get_json() == {
        "status": "success",
        "data": {"id": "server-1", "name": "web01"},
    }
    assert client.get("/api/v1/networks").get_json()["data"][0]["id"] == "network-1"
    assert client.get("/api/v1/images").get_json()["data"][0]["id"] == "image-1"
    assert client.get("/api/v1/flavors").get_json()["data"][0]["id"] == "flavor-1"


def test_api_route_errors_use_standard_error_envelope() -> None:
    app = create_app(Settings(api_key="test-key", testing=True))
    app.extensions["openstack_service"] = FakeRouteService()
    client = app.test_client()

    response = client.get("/api/v1/servers/missing")

    assert response.status_code == 404
    assert response.get_json() == {
        "status": "error",
        "message": "OpenStack server was not found.",
        "code": 404,
    }
