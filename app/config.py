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
    inventory_scope: str | None = None
    inventory_max_age_seconds: int = 900
    mysql_host: str | None = None
    mysql_port: int = 3306
    mysql_database: str | None = None
    mysql_username: str | None = None
    mysql_password: str | None = None
    mysql_charset: str = "utf8mb4"
    mysql_pool_size: int = 5
    mysql_max_overflow: int = 10
    mysql_pool_recycle: int = 1800
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
            inventory_scope=_env("INVENTORY_SCOPE"),
            inventory_max_age_seconds=_env_int("INVENTORY_MAX_AGE_SECONDS", 900),
            mysql_host=_env("MYSQL_HOST"),
            mysql_port=_env_int("MYSQL_PORT", 3306),
            mysql_database=_env("MYSQL_DATABASE"),
            mysql_username=_env("MYSQL_USERNAME"),
            mysql_password=_env("MYSQL_PASSWORD"),
            mysql_charset=_env("MYSQL_CHARSET", "utf8mb4") or "utf8mb4",
            mysql_pool_size=_env_int("MYSQL_POOL_SIZE", 5),
            mysql_max_overflow=_env_int("MYSQL_MAX_OVERFLOW", 10),
            mysql_pool_recycle=_env_int("MYSQL_POOL_RECYCLE", 1800),
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

    def validate_inventory(self) -> None:
        """Raise ConfigurationError when inventory database config is invalid."""
        required_values = {
            "INVENTORY_SCOPE": self.inventory_scope,
            "MYSQL_HOST": self.mysql_host,
            "MYSQL_DATABASE": self.mysql_database,
            "MYSQL_USERNAME": self.mysql_username,
            "MYSQL_PASSWORD": self.mysql_password,
            "MYSQL_CHARSET": self.mysql_charset,
        }
        missing = [name for name, value in required_values.items() if not value]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ConfigurationError(
                f"Missing required inventory database settings: {joined}"
            )

        if not 1 <= self.mysql_port <= 65535:
            raise ConfigurationError("MYSQL_PORT must be between 1 and 65535.")
        if self.mysql_pool_size < 1:
            raise ConfigurationError("MYSQL_POOL_SIZE must be at least 1.")
        if self.mysql_max_overflow < 0:
            raise ConfigurationError("MYSQL_MAX_OVERFLOW must be 0 or greater.")
        if self.mysql_pool_recycle < 1:
            raise ConfigurationError("MYSQL_POOL_RECYCLE must be at least 1.")
        if self.inventory_max_age_seconds < 0:
            raise ConfigurationError("INVENTORY_MAX_AGE_SECONDS must be 0 or greater.")

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


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer.") from error
