from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_IDENTITY_API_VERSION = "3"
DEFAULT_INTERFACE = "public"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    flask_env: str = "production"
    flask_debug: bool = False
    api_key: str | None = None
    os_auth_url: str | None = None
    os_application_credential_id: str | None = None
    os_application_credential_secret: str | None = None
    os_project_id: str | None = None
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
            os_auth_url=_env("OS_AUTH_URL"),
            os_application_credential_id=_env("OS_APPLICATION_CREDENTIAL_ID"),
            os_application_credential_secret=_env("OS_APPLICATION_CREDENTIAL_SECRET"),
            os_project_id=_env("OS_PROJECT_ID"),
            os_region_name=_env("OS_REGION_NAME"),
            os_interface=_env("OS_INTERFACE", DEFAULT_INTERFACE) or DEFAULT_INTERFACE,
            os_identity_api_version=_env(
                "OS_IDENTITY_API_VERSION", DEFAULT_IDENTITY_API_VERSION
            )
            or DEFAULT_IDENTITY_API_VERSION,
        )

    @property
    def openstack_auth(self) -> dict[str, str]:
        """Return OpenStack SDK auth parameters for application credentials."""
        self.validate_openstack()

        auth = {
            "auth_url": self.os_auth_url or "",
            "application_credential_id": self.os_application_credential_id or "",
            "application_credential_secret": self.os_application_credential_secret
            or "",
        }
        if self.os_project_id:
            auth["project_id"] = self.os_project_id
        return auth

    def validate_openstack(self) -> None:
        """Raise ValueError when required OpenStack configuration is missing."""
        required_values = {
            "OS_AUTH_URL": self.os_auth_url,
            "OS_APPLICATION_CREDENTIAL_ID": self.os_application_credential_id,
            "OS_APPLICATION_CREDENTIAL_SECRET": (self.os_application_credential_secret),
        }
        missing = [name for name, value in required_values.items() if not value]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ValueError(f"Missing required OpenStack settings: {joined}")


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
