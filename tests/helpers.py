from __future__ import annotations

from typing import Any

from flask import Flask
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app import create_app
from app.config import Settings
from app.services.inventory_query import InventoryQueryService


def inventory_settings(scope: str = "appdev", **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "api_key": "test-key",
        "testing": True,
        "inventory_scope": scope,
        "mysql_host": "127.0.0.1",
        "mysql_database": "openstack_inventory",
        "mysql_username": "openstack_api",
        "mysql_password": "secret-password",
    }
    values.update(overrides)
    return Settings(**values)


def make_inventory_app(engine: Engine, scope: str = "appdev") -> Flask:
    settings = inventory_settings(scope)
    app = create_app(settings)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    app.extensions["inventory_query_service"] = InventoryQueryService(
        settings=settings,
        session_factory=session_factory,
        logger=app.logger,
    )
    return app
