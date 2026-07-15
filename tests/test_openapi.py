from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from app import create_app
from app.config import ConfigurationError, Settings
from app.openapi import SECURITY_SCHEME_NAME, build_openapi_spec
from tests.helpers import inventory_settings

SWAGGER_ASSETS = {
    "/docs/assets/swagger-ui.css": {"text/css"},
    "/docs/assets/swagger-ui-bundle.js": {"application/javascript", "text/javascript"},
    "/docs/assets/swagger-ui-standalone-preset.js": {
        "application/javascript",
        "text/javascript",
    },
}


def test_swagger_ui_and_spec_are_served_when_enabled() -> None:
    app = create_app(inventory_settings())
    client = app.test_client()

    docs_response = client.get("/docs")
    spec_response = client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert docs_response.mimetype == "text/html"
    assert "SwaggerUIBundle" in docs_response.get_data(as_text=True)
    assert spec_response.status_code == 200
    assert spec_response.mimetype == "application/json"
    payload = spec_response.get_json()
    assert payload["openapi"].startswith("3.")
    assert "/api/v1/servers" in payload["paths"]
    assert "/api/v1/servers/{server_id}" in payload["paths"]


def test_swagger_html_references_valid_local_application_urls() -> None:
    app = create_app(inventory_settings())
    html = app.test_client().get("/docs").get_data(as_text=True)

    assert 'href="/docs/assets/swagger-ui.css"' in html
    assert 'src="/docs/assets/swagger-ui-bundle.js"' in html
    assert 'src="/docs/assets/swagger-ui-standalone-preset.js"' in html
    assert 'url: "/openapi.json"' in html
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()


@pytest.mark.parametrize(("path", "expected_mimetypes"), SWAGGER_ASSETS.items())
def test_swagger_assets_are_served_with_expected_mime_types(
    path: str,
    expected_mimetypes: set[str],
) -> None:
    app = create_app(inventory_settings())

    response = app.test_client().get(path)

    assert response.status_code == 200
    assert response.mimetype in expected_mimetypes
    assert response.get_data()


def test_openapi_json_returns_valid_json() -> None:
    app = create_app(inventory_settings())

    response = app.test_client().get("/openapi.json")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.get_json()["openapi"] == "3.0.3"


def test_swagger_remains_functional_with_custom_openapi_paths() -> None:
    app = create_app(
        inventory_settings(
            openapi_docs_path="/internal/docs",
            openapi_spec_path="/internal/openapi.json",
        )
    )
    client = app.test_client()

    docs_response = client.get("/internal/docs")
    html = docs_response.get_data(as_text=True)

    assert docs_response.status_code == 200
    assert 'href="/internal/docs/assets/swagger-ui.css"' in html
    assert 'src="/internal/docs/assets/swagger-ui-bundle.js"' in html
    assert 'src="/internal/docs/assets/swagger-ui-standalone-preset.js"' in html
    assert 'url: "/internal/openapi.json"' in html
    assert client.get("/internal/docs/assets/swagger-ui.css").status_code == 200
    assert client.get("/internal/docs/assets/swagger-ui-bundle.js").status_code == 200
    assert (
        client.get("/internal/docs/assets/swagger-ui-standalone-preset.js").status_code
        == 200
    )
    assert client.get("/internal/openapi.json").status_code == 200


def test_swagger_urls_respect_trusted_proxy_prefix() -> None:
    app = create_app(
        inventory_settings(
            trust_proxy_headers=True,
            proxy_fix_x_prefix=1,
        )
    )

    response = app.test_client().get(
        "/docs",
        headers={"X-Forwarded-Prefix": "/proxy-prefix"},
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/proxy-prefix/docs/assets/swagger-ui.css"' in html
    assert 'src="/proxy-prefix/docs/assets/swagger-ui-bundle.js"' in html
    assert 'src="/proxy-prefix/docs/assets/swagger-ui-standalone-preset.js"' in html
    assert 'url: "/proxy-prefix/openapi.json"' in html


def test_swagger_ui_and_spec_are_404_when_disabled() -> None:
    app = create_app(inventory_settings(openapi_enabled=False))
    client = app.test_client()

    assert client.get("/docs").status_code == 404
    assert client.get("/docs/assets/swagger-ui.css").status_code == 404
    assert client.get("/docs/assets/swagger-ui-bundle.js").status_code == 404
    assert client.get("/docs/assets/swagger-ui-standalone-preset.js").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/docs/assets/../openapi.py",
        "/docs/assets/%2e%2e/openapi.py",
        "/docs/assets/../../pyproject.toml",
    ],
)
def test_swagger_asset_route_rejects_path_traversal(path: str) -> None:
    app = create_app(inventory_settings())

    response = app.test_client().get(path)

    assert response.status_code == 404


def test_swagger_ui_bundle_is_a_runtime_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = pyproject["project"]["dependencies"]
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(
        dependency.startswith("swagger-ui-bundle")
        for dependency in runtime_dependencies
    )
    assert not any(
        dependency.startswith("swagger-ui-bundle") for dependency in dev_dependencies
    )


def test_openapi_spec_documents_bearer_key_but_keeps_get_routes_public() -> None:
    spec = build_openapi_spec().to_dict()

    assert spec["components"]["securitySchemes"][SECURITY_SCHEME_NAME] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API key",
        "description": "Supply the API key as Authorization: Bearer <API_KEY>.",
    }
    assert "security" not in spec
    for path_item in spec["paths"].values():
        operation = path_item["get"]
        assert "security" not in operation


def test_openapi_spec_keeps_unpaginated_contract() -> None:
    spec = build_openapi_spec().to_dict()
    parameter_names = {
        parameter["name"]
        for path_item in spec["paths"].values()
        for parameter in path_item["get"].get("parameters", [])
    }

    assert "page" not in parameter_names
    assert "per_page" not in parameter_names


def test_openapi_spec_documents_repeatable_tag_filter() -> None:
    spec = build_openapi_spec().to_dict()
    parameters = spec["paths"]["/api/v1/servers"]["get"]["parameters"]
    tag_parameter = _parameter_by_name(parameters, "tag")

    assert tag_parameter["style"] == "form"
    assert tag_parameter["explode"] is True
    assert tag_parameter["schema"] == {"type": "array", "items": {"type": "string"}}


def test_openapi_spec_contains_public_response_components() -> None:
    spec = build_openapi_spec().to_dict()
    schemas = spec["components"]["schemas"]

    assert "ErrorResponse" in schemas
    assert "ServerCollectionResponse" in schemas
    server_ref = schemas["ServerCollectionResponse"]["properties"]["data"]["items"][
        "$ref"
    ]
    assert server_ref.endswith("/Server")
    assert "auth_url" not in str(spec)
    assert "secret-password" not in str(spec)


def test_openapi_export_command_writes_schema_without_app_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_from_env() -> Settings:
        raise AssertionError("OpenAPI export should not create the Flask app")

    monkeypatch.setattr("app.config.Settings.from_env", fail_from_env)

    from app.openapi import main

    output = tmp_path / "openapi.json"
    monkeypatch.setattr(
        "sys.argv",
        ["python -m app.openapi", "export", "--output", str(output)],
    )

    main()

    assert output.exists()
    assert '"openapi": "3.0.3"' in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("openapi_docs_path", "docs", "OPENAPI_DOCS_PATH"),
        ("openapi_docs_path", "/api", "OPENAPI_DOCS_PATH"),
        ("openapi_spec_path", "/api/v1/openapi.json", "OPENAPI_SPEC_PATH"),
        ("openapi_spec_path", "/health", "OPENAPI_SPEC_PATH"),
    ],
)
def test_openapi_paths_are_validated(field: str, value: str, match: str) -> None:
    settings = inventory_settings(**{field: value})

    with pytest.raises(ConfigurationError, match=match):
        settings.validate_openapi()


def test_openapi_docs_and_spec_paths_must_differ() -> None:
    settings = inventory_settings(openapi_docs_path="/docs", openapi_spec_path="/docs")

    with pytest.raises(ConfigurationError, match="must be different"):
        settings.validate_openapi()


def test_proxy_hop_counts_are_validated() -> None:
    settings = inventory_settings(proxy_fix_x_for=-1)

    with pytest.raises(ConfigurationError, match="PROXY_FIX_X_FOR"):
        settings.validate_proxy()


def test_boolean_openapi_and_proxy_settings_parse_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAPI_ENABLED", "false")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")

    settings = Settings.from_env()

    assert settings.openapi_enabled is False
    assert settings.trust_proxy_headers is True


def _parameter_by_name(
    parameters: list[dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    return next(parameter for parameter in parameters if parameter["name"] == name)
