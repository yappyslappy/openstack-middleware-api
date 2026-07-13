from __future__ import annotations

from flask import Flask

from app.config import Settings
from app.errors.handlers import register_error_handlers
from app.middleware.auth import register_auth_middleware
from app.routes.health import bp as health_bp
from app.routes.openstack import bp as openstack_bp
from app.utils.logging import configure_logging, register_request_logging


def create_app(settings: Settings | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app_settings = settings or Settings.from_env()
    app_settings.validate_inventory()

    app.config.update(
        ENV=app_settings.flask_env,
        DEBUG=app_settings.flask_debug,
        TESTING=app_settings.testing,
    )
    app.config["SETTINGS"] = app_settings

    configure_logging(app)
    register_request_logging(app)
    register_auth_middleware(app)
    register_error_handlers(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(openstack_bp)

    return app
