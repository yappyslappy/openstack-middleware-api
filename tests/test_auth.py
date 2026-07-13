from __future__ import annotations

from flask import Flask


def test_mutating_request_without_authorization_returns_401(
    inventory_app: Flask,
) -> None:
    app = inventory_app
    client = app.test_client()

    response = client.post("/health")

    assert response.status_code == 401
    assert response.get_json() == {
        "status": "error",
        "message": "Authorization header is required.",
        "code": 401,
    }


def test_mutating_request_with_invalid_api_key_returns_403(
    inventory_app: Flask,
) -> None:
    app = inventory_app
    client = app.test_client()

    response = client.post("/health", headers={"Authorization": "Bearer wrong-key"})

    assert response.status_code == 403
    assert response.get_json() == {
        "status": "error",
        "message": "Invalid API key.",
        "code": 403,
    }


def test_mutating_request_with_valid_api_key_reaches_route_matching(
    inventory_app: Flask,
) -> None:
    app = inventory_app
    client = app.test_client()

    response = client.post("/health", headers={"Authorization": "Bearer test-key"})

    assert response.status_code == 405
    assert response.get_json() == {
        "status": "error",
        "message": "Method not allowed.",
        "code": 405,
    }


def test_get_request_does_not_require_authorization(inventory_app: Flask) -> None:
    app = inventory_app
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
