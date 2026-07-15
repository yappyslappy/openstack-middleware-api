from __future__ import annotations

import tomllib
from pathlib import Path
from runpy import run_path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_hardened_gunicorn_runtime() -> None:
    dockerfile = _read("Dockerfile")

    assert "FROM python:3.12-slim AS builder" in dockerfile
    assert "FROM python:3.12-slim AS runtime" in dockerfile
    assert "USER app" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["gunicorn", "run:app", "-c", "docker/gunicorn.conf.py"]' in dockerfile
    assert ".env" not in dockerfile


def test_docker_image_installs_runtime_swagger_asset_package() -> None:
    dockerfile = _read("Dockerfile")
    pyproject = tomllib.loads(_read("pyproject.toml"))
    runtime_dependencies = pyproject["project"]["dependencies"]
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    assert "RUN pip install --no-cache-dir ." in dockerfile
    assert '".[dev]"' not in dockerfile
    assert any(
        dependency.startswith("swagger-ui-bundle")
        for dependency in runtime_dependencies
    )
    assert not any(
        dependency.startswith("swagger-ui-bundle") for dependency in dev_dependencies
    )


def test_dockerignore_excludes_local_state_and_tests() -> None:
    dockerignore = _read(".dockerignore").splitlines()

    assert ".git" in dockerignore
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert ".venv" in dockerignore
    assert "tests" in dockerignore


def test_compose_uses_external_database_and_restricted_runtime() -> None:
    compose = _read("docker-compose.yml")

    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose
    assert "- ALL" in compose
    assert "- /tmp" in compose
    assert "healthcheck:" in compose
    assert "mysql:" not in compose.lower()
    assert "privileged:" not in compose.lower()
    assert "docker.sock" not in compose.lower()


def test_docker_environment_example_has_no_deprecated_scope() -> None:
    env_example = _read(".env.docker.example")

    assert "INVENTORY_SCOPE" not in env_example
    assert "MYSQL_HOST=<MYSQL_HOST>" in env_example
    assert "OPENAPI_ENABLED=true" in env_example
    assert "TRUST_PROXY_HEADERS=false" in env_example


def test_gunicorn_config_has_production_defaults() -> None:
    config: dict[str, Any] = run_path(str(ROOT / "docker/gunicorn.conf.py"))

    assert config["bind"] == "0.0.0.0:8000"
    assert config["workers"] == 4
    assert config["threads"] == 2
    assert config["accesslog"] == "-"
    assert config["errorlog"] == "-"
    assert config["forwarded_allow_ips"] == "127.0.0.1"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")
