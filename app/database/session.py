from __future__ import annotations

import atexit
from typing import cast

from flask import Flask
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database.engine import create_inventory_engine


def get_inventory_session_factory(app: Flask) -> sessionmaker[Session]:
    """Return the app-local inventory session factory, creating it lazily."""
    session_factory = app.extensions.get("inventory_session_factory")
    if session_factory is not None:
        return cast(sessionmaker[Session], session_factory)

    settings = cast(Settings, app.config["SETTINGS"])
    engine = create_inventory_engine(settings)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    app.extensions["inventory_engine"] = engine
    app.extensions["inventory_session_factory"] = session_factory
    atexit.register(engine.dispose)

    return session_factory


def dispose_inventory_engine(app: Flask) -> None:
    """Dispose of the inventory engine if this app created one."""
    engine = app.extensions.pop("inventory_engine", None)
    app.extensions.pop("inventory_session_factory", None)
    if isinstance(engine, Engine):
        engine.dispose()
