from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_IDENTITY_API_VERSION = "3"
DEFAULT_INTERFACE = "public"
DEFAULT_OPENSTACK_AUTH_TYPE = "application_credential"
SUPPORTED_OPENSTACK_AUTH_TYPES = frozenset({DEFAULT_OPENSTACK_AUTH_TYPE, "password"})


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    flask_env: str = "production"
    flask_debug: bool = False
    api_key: str | None = None
    os_auth_type: str | None = DEFAULT_OPENSTACK_AUTH_TYPE
    os_auth_url: str | None = None
    os_application_credential_id: str | None = None
    os_application_credential_secret: str | None = None
    os_username: str | None = None
    os_password: str | None = None
    os_user_domain_name: str | None = None
    os_project_id: str | None = None
    os_project_name: str | None = None
    os_project_domain_name: str | None = None
    os_region_name: str | None = None
    os_interface: str = DEFAULT_INTERFACE
    os_identity_api_version: str = DEFAULT_IDENTITY_API_VERSION
    testing: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from process environment variables."""
        load_dotenv()

        return cls(
            flask_env=_env("FLASK_ENV", "production") or "production",
            flask_debug=_env_bool("FLASK_DEBUG"),
            api_key=_env("API_KEY"),
            os_auth_type=_env("OS_AUTH_TYPE", DEFAULT_OPENSTACK_AUTH_TYPE),
            os_auth_url=_env("OS_AUTH_URL"),
            os_application_credential_id=_env("OS_APPLICATION_CREDENTIAL_ID"),
            os_application_credential_secret=_env("OS_APPLICATION_CREDENTIAL_SECRET"),
            os_username=_env("OS_USERNAME"),
            os_password=_env("OS_PASSWORD"),
            os_user_domain_name=_env("OS_USER_DOMAIN_NAME"),
            os_project_id=_env("OS_PROJECT_ID"),
            os_project_name=_env("OS_PROJECT_NAME"),
            os_project_domain_name=_env("OS_PROJECT_DOMAIN_NAME"),
            os_region_name=_env("OS_REGION_NAME"),
            os_interface=_env("OS_INTERFACE", DEFAULT_INTERFACE) or DEFAULT_INTERFACE,
            os_identity_api_version=_env(
                "OS_IDENTITY_API_VERSION", DEFAULT_IDENTITY_API_VERSION
            )
            or DEFAULT_IDENTITY_API_VERSION,
        )

    @property
    def resolved_openstack_auth_type(self) -> str:
        """Return the validated OpenStack auth mode."""
        auth_type = (self.os_auth_type or "").strip().lower()
        if not auth_type:
            raise ConfigurationError("OS_AUTH_TYPE is required.")
        if auth_type not in SUPPORTED_OPENSTACK_AUTH_TYPES:
            supported = ", ".join(sorted(SUPPORTED_OPENSTACK_AUTH_TYPES))
            raise ConfigurationError(
                f"Unsupported OS_AUTH_TYPE '{auth_type}'. "
                f"Supported values: {supported}."
            )
        return auth_type

    def validate_openstack(self) -> None:
        """Raise ConfigurationError when OpenStack configuration is invalid."""
        auth_type = self.resolved_openstack_auth_type
        required_values = {"OS_AUTH_URL": self.os_auth_url}
        if auth_type == DEFAULT_OPENSTACK_AUTH_TYPE:
            required_values.update(
                {
                    "OS_APPLICATION_CREDENTIAL_ID": (self.os_application_credential_id),
                    "OS_APPLICATION_CREDENTIAL_SECRET": (
                        self.os_application_credential_secret
                    ),
                }
            )
        elif auth_type == "password":
            required_values.update(
                {
                    "OS_USERNAME": self.os_username,
                    "OS_PASSWORD": self.os_password,
                    "OS_USER_DOMAIN_NAME": self.os_user_domain_name,
                    "OS_PROJECT_NAME": self.os_project_name,
                    "OS_PROJECT_DOMAIN_NAME": self.os_project_domain_name,
                }
            )

        missing = [name for name, value in required_values.items() if not value]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ConfigurationError(
                f"Missing required OpenStack settings for "
                f"{auth_type} auth: {joined}"
            )


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "t", "yes", "y", "on"}
