from __future__ import annotations

from app import create_app
from app.config import Settings


def test_health_endpoint_is_public() -> None:
    app = create_app(Settings(api_key="test-key", testing=True))
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {
            "service": "openstack-middleware-api",
            "status": "ok",
        },
    }
