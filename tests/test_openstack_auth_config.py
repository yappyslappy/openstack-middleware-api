from __future__ import annotations

from typing import Any

import pytest

from app.config import (
    DEFAULT_OPENSTACK_AUTH_TYPE,
    ConfigurationError,
    Settings,
)
from app.services import openstack_client
from app.services.openstack_client import OpenStackClient


def test_unset_env_auth_type_defaults_to_application_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OS_AUTH_TYPE", raising=False)
    monkeypatch.setenv("OS_AUTH_URL", "https://openstack.example/v3")
    monkeypatch.setenv("OS_APPLICATION_CREDENTIAL_ID", "credential-id")
    monkeypatch.setenv("OS_APPLICATION_CREDENTIAL_SECRET", "credential-secret")

    settings = Settings.from_env()

    assert settings.resolved_openstack_auth_type == DEFAULT_OPENSTACK_AUTH_TYPE


def test_application_credential_auth_config_generation() -> None:
    settings = _application_credential_settings()

    config = OpenStackClient(settings)._build_auth_config()

    assert config == {
        "auth_type": "v3applicationcredential",
        "auth": {
            "auth_url": "https://openstack.example/v3",
            "application_credential_id": "credential-id",
            "application_credential_secret": "credential-secret",
        },
    }


def test_application_credential_auth_does_not_pass_project_scope() -> None:
    settings = _application_credential_settings(
        os_project_id="project-id",
        os_project_name="demo",
        os_project_domain_name="Default",
        os_user_domain_name="Default",
    )

    config = OpenStackClient(settings)._build_auth_config()

    auth = config["auth"]
    assert "project_id" not in auth
    assert "project_name" not in auth
    assert "project_domain_name" not in auth
    assert "user_domain_name" not in auth


def test_password_auth_config_generation() -> None:
    settings = _password_settings()

    config = OpenStackClient(settings)._build_auth_config()

    assert config == {
        "auth_type": "v3password",
        "auth": {
            "auth_url": "https://openstack.example/v3",
            "username": "demo-user",
            "password": "secret-password",
            "user_domain_name": "Default",
            "project_name": "demo-project",
            "project_domain_name": "Default",
        },
    }


def test_connect_uses_auth_config_and_common_openstack_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openstack_client, "openstack_connect", fake_connect)
    settings = _password_settings(
        os_region_name="RegionOne",
        os_interface="internal",
        os_identity_api_version="3",
    )

    connection = OpenStackClient(settings).connection

    assert connection is not None
    assert captured["auth_type"] == "v3password"
    assert captured["region_name"] == "RegionOne"
    assert captured["interface"] == "internal"
    assert captured["identity_api_version"] == "3"
    assert captured["app_name"] == "openstack-middleware-api"
    assert captured["timeout"] == 30


def test_missing_auth_type_configuration_raises_clear_error() -> None:
    settings = _application_credential_settings(os_auth_type=None)

    with pytest.raises(ConfigurationError, match="OS_AUTH_TYPE is required"):
        OpenStackClient(settings)._build_auth_config()


def test_unsupported_auth_type_configuration_raises_clear_error() -> None:
    settings = _application_credential_settings(os_auth_type="token")

    with pytest.raises(ConfigurationError, match="Unsupported OS_AUTH_TYPE"):
        OpenStackClient(settings)._build_auth_config()


def test_missing_application_credential_variables_raise_clear_error() -> None:
    settings = _application_credential_settings(
        os_application_credential_id=None,
        os_application_credential_secret=None,
    )

    with pytest.raises(ConfigurationError) as error_info:
        OpenStackClient(settings)._build_auth_config()

    message = str(error_info.value)
    assert "application_credential auth" in message
    assert "OS_APPLICATION_CREDENTIAL_ID" in message
    assert "OS_APPLICATION_CREDENTIAL_SECRET" in message
    assert "credential-secret" not in message


def test_missing_password_variables_raise_clear_error() -> None:
    settings = _password_settings(
        os_password=None,
        os_project_domain_name=None,
    )

    with pytest.raises(ConfigurationError) as error_info:
        OpenStackClient(settings)._build_auth_config()

    message = str(error_info.value)
    assert "password auth" in message
    assert "OS_PASSWORD" in message
    assert "OS_PROJECT_DOMAIN_NAME" in message
    assert "secret-password" not in message


def _application_credential_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "os_auth_type": "application_credential",
        "os_auth_url": "https://openstack.example/v3",
        "os_application_credential_id": "credential-id",
        "os_application_credential_secret": "credential-secret",
        "testing": True,
    }
    values.update(overrides)
    return Settings(**values)


def _password_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "os_auth_type": "password",
        "os_auth_url": "https://openstack.example/v3",
        "os_username": "demo-user",
        "os_password": "secret-password",
        "os_user_domain_name": "Default",
        "os_project_name": "demo-project",
        "os_project_domain_name": "Default",
        "testing": True,
    }
    values.update(overrides)
    return Settings(**values)
