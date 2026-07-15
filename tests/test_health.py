from __future__ import annotations

from flask import Flask


def test_health_endpoint_is_public(inventory_app: Flask) -> None:
    app = inventory_app
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["application"] == "healthy"
    assert data["database"] == "healthy"
    assert data["active_inventory_sources"] == 2
    assert data["stale_inventory_sources"] == 0
