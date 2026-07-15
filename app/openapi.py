from __future__ import annotations

import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from flask import Flask, abort, jsonify, render_template_string, send_from_directory

from app.config import Settings
from app.schemas.common import ErrorResponseSchema
from app.schemas.flavor import FlavorCollectionResponseSchema
from app.schemas.health import HealthResponseSchema
from app.schemas.image import ImageCollectionResponseSchema
from app.schemas.inventory_source import InventorySourceCollectionResponseSchema
from app.schemas.network import NetworkCollectionResponseSchema
from app.schemas.project import ProjectCollectionResponseSchema
from app.schemas.server import ServerCollectionResponseSchema, ServerResponseSchema

OPENAPI_TITLE = "OpenStack Middleware API"
OPENAPI_VERSION = "3.0.3"
OPENAPI_DESCRIPTION = (
    "Read-only inventory API backed by the OpenStack inventory MySQL database, "
    "with protected future OpenStack write operations."
)
SECURITY_SCHEME_NAME = "BearerApiKey"

SWAGGER_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="{{ asset_base }}/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="{{ asset_base }}/swagger-ui-bundle.js"></script>
    <script src="{{ asset_base }}/swagger-ui-standalone-preset.js"></script>
    <script>
      window.onload = function() {
        window.ui = SwaggerUIBundle({
          url: "{{ spec_path }}",
          dom_id: "#swagger-ui",
          deepLinking: true,
          presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIStandalonePreset
          ],
          layout: "StandaloneLayout"
        });
      };
    </script>
  </body>
</html>
"""


def register_openapi(app: Flask) -> None:
    """Register OpenAPI JSON and Swagger UI routes when enabled."""
    settings = cast(Settings, app.config["SETTINGS"])
    if not settings.openapi_enabled:
        return

    docs_path = settings.openapi_docs_path
    spec_path = settings.openapi_spec_path
    asset_path = f"{docs_path}/assets/<path:filename>"
    asset_base = f"{docs_path}/assets"

    def openapi_json() -> Any:
        return jsonify(build_openapi_spec().to_dict())

    def docs() -> str:
        return render_template_string(
            SWAGGER_TEMPLATE,
            title=OPENAPI_TITLE,
            spec_path=spec_path,
            asset_base=asset_base,
        )

    def docs_asset(filename: str) -> Any:
        swagger_path = _swagger_ui_path()
        if swagger_path is None:
            abort(404)
        return send_from_directory(swagger_path, filename)

    app.add_url_rule(spec_path, "openapi_json", openapi_json, methods=["GET"])
    app.add_url_rule(docs_path, "swagger_ui", docs, methods=["GET"])
    app.add_url_rule(asset_path, "swagger_ui_asset", docs_asset, methods=["GET"])


def build_openapi_spec() -> APISpec:
    """Build the OpenAPI schema without connecting to MySQL or OpenStack."""
    spec = APISpec(
        title=OPENAPI_TITLE,
        version=_package_version(),
        openapi_version=OPENAPI_VERSION,
        info={"description": OPENAPI_DESCRIPTION},
        plugins=[MarshmallowPlugin()],
    )
    _register_components(spec)
    _register_paths(spec)
    return spec


def main() -> None:
    """Command-line schema export entry point."""
    parser = argparse.ArgumentParser(description="Export the OpenAPI schema.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export", help="Export OpenAPI JSON.")
    export_parser.add_argument("--output", required=True, help="Output JSON path.")
    args = parser.parse_args()

    if args.command == "export":
        output = Path(args.output)
        output.write_text(
            json.dumps(build_openapi_spec().to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _register_components(spec: APISpec) -> None:
    spec.components.security_scheme(
        SECURITY_SCHEME_NAME,
        {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API key",
            "description": "Supply the API key as Authorization: Bearer <API_KEY>.",
        },
    )
    for name, schema in {
        "ErrorResponse": ErrorResponseSchema,
        "HealthResponse": HealthResponseSchema,
        "InventorySourceCollectionResponse": InventorySourceCollectionResponseSchema,
        "ProjectCollectionResponse": ProjectCollectionResponseSchema,
        "ServerCollectionResponse": ServerCollectionResponseSchema,
        "ServerResponse": ServerResponseSchema,
        "NetworkCollectionResponse": NetworkCollectionResponseSchema,
        "ImageCollectionResponse": ImageCollectionResponseSchema,
        "FlavorCollectionResponse": FlavorCollectionResponseSchema,
    }.items():
        spec.components.schema(name, schema=schema)


def _register_paths(spec: APISpec) -> None:
    spec.path(
        path="/health",
        operations={
            "get": _operation(
                "Health",
                "Return application, database, and inventory-source health.",
                "HealthResponse",
                errors=[503],
            )
        },
    )
    spec.path(
        path="/api/v1/inventory-sources",
        operations={
            "get": _operation(
                "Inventory Sources",
                "Return safe metadata for active inventory sources.",
                "InventorySourceCollectionResponse",
                parameters=_source_filter_parameters(),
                errors=[400, 503],
            )
        },
    )
    spec.path(
        path="/api/v1/projects",
        operations={
            "get": _operation(
                "Projects",
                "Return active projects across all active inventory sources.",
                "ProjectCollectionResponse",
                parameters=[*_source_filter_parameters(), *_sort_parameters()],
                errors=[400, 503],
            )
        },
    )
    spec.path(
        path="/api/v1/servers",
        operations={
            "get": _operation(
                "Servers",
                "Return all matching active servers without implicit pagination.",
                "ServerCollectionResponse",
                parameters=[
                    *_source_filter_parameters(),
                    *_server_filter_parameters(),
                    _tag_parameter(),
                    *_sort_parameters(),
                ],
                errors=[400, 503],
            )
        },
    )
    spec.path(
        path="/api/v1/servers/{server_id}",
        operations={
            "get": _operation(
                "Servers",
                "Return one active server, or 409 when the ID is ambiguous.",
                "ServerResponse",
                parameters=[
                    {
                        "name": "server_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    *_source_filter_parameters(),
                ],
                errors=[400, 404, 409, 503],
            )
        },
    )
    for path, tag, description, schema in [
        (
            "/api/v1/networks",
            "Networks",
            "Return active networks across all active inventory sources.",
            "NetworkCollectionResponse",
        ),
        (
            "/api/v1/images",
            "Images",
            "Return active images across all active inventory sources.",
            "ImageCollectionResponse",
        ),
        (
            "/api/v1/flavors",
            "Flavors",
            "Return active flavors across all active inventory sources.",
            "FlavorCollectionResponse",
        ),
    ]:
        spec.path(
            path=path,
            operations={
                "get": _operation(
                    tag,
                    description,
                    schema,
                    parameters=[*_source_filter_parameters(), *_sort_parameters()],
                    errors=[400, 503],
                )
            },
        )


def _operation(
    tag: str,
    description: str,
    response_schema: str,
    *,
    parameters: list[dict[str, Any]] | None = None,
    errors: list[int] | None = None,
) -> dict[str, Any]:
    responses = {
        "200": {
            "description": "Successful response.",
            "content": _json_schema_ref(response_schema),
        }
    }
    for code in errors or []:
        responses[str(code)] = {
            "description": _error_description(code),
            "content": _json_schema_ref("ErrorResponse"),
        }
    return {
        "tags": [tag],
        "description": description,
        "parameters": parameters or [],
        "responses": responses,
    }


def _source_filter_parameters() -> list[dict[str, Any]]:
    return [
        _query_parameter("scope", "Inventory source scope."),
        _query_parameter("project_id", "OpenStack project UUID for the source."),
        _query_parameter("project_name", "OpenStack project name for the source."),
        _query_parameter("region", "OpenStack region name for the source."),
    ]


def _server_filter_parameters() -> list[dict[str, Any]]:
    return [
        _query_parameter("name", "Server name."),
        _query_parameter("status", "Server status."),
        _query_parameter("availability_zone", "Availability zone."),
        _query_parameter("compute_host", "Compute host."),
        _query_parameter("power_state", "Power state."),
        _query_parameter("vm_state", "VM state."),
    ]


def _sort_parameters() -> list[dict[str, Any]]:
    return [
        _query_parameter("sort", "Allowlisted sort field."),
        _query_parameter("order", "Sort order: asc or desc."),
    ]


def _tag_parameter() -> dict[str, Any]:
    return {
        "name": "tag",
        "in": "query",
        "required": False,
        "description": (
            "Repeatable server tag filter. Multiple tag parameters use AND semantics."
        ),
        "style": "form",
        "explode": True,
        "schema": {"type": "array", "items": {"type": "string"}},
    }


def _query_parameter(name: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": {"type": "string"},
    }


def _json_schema_ref(schema_name: str) -> dict[str, Any]:
    return {
        "application/json": {"schema": {"$ref": f"#/components/schemas/{schema_name}"}}
    }


def _error_description(code: int) -> str:
    descriptions = {
        400: "Bad request.",
        404: "Resource not found.",
        409: "Ambiguous resource.",
        503: "Service unavailable.",
    }
    return descriptions.get(code, "Error response.")


def _package_version() -> str:
    try:
        return version("openstack-middleware-api")
    except PackageNotFoundError:
        return "0.1.0"


def _swagger_ui_path() -> str | None:
    try:
        from swagger_ui_bundle import swagger_ui_3_path
    except ImportError:
        return None
    return str(swagger_ui_3_path)


if __name__ == "__main__":
    main()
