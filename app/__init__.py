from __future__ import annotations

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

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
    app_settings.validate_openapi()
    app_settings.validate_proxy()
    if app_settings.inventory_scope:
        app.logger.warning("inventory_scope_deprecated_ignored")

    app.config.update(
        ENV=app_settings.flask_env,
        DEBUG=app_settings.flask_debug,
        TESTING=app_settings.testing,
    )
    app.config["SETTINGS"] = app_settings
    if app_settings.trust_proxy_headers:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app,
            x_for=app_settings.proxy_fix_x_for,
            x_proto=app_settings.proxy_fix_x_proto,
            x_host=app_settings.proxy_fix_x_host,
            x_port=app_settings.proxy_fix_x_port,
            x_prefix=app_settings.proxy_fix_x_prefix,
        )

    configure_logging(app)
    register_request_logging(app)
    register_auth_middleware(app)
    register_error_handlers(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(openstack_bp)

    from app.openapi import register_openapi

    register_openapi(app)

    return app
