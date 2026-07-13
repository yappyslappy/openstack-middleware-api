from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from app.config import Settings


def build_database_url(settings: Settings) -> URL:
    """Build a credential-safe SQLAlchemy URL for the inventory database."""
    settings.validate_inventory()
    return URL.create(
        "mysql+pymysql",
        username=settings.mysql_username,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        query={"charset": settings.mysql_charset},
    )


def create_inventory_engine(settings: Settings) -> Engine:
    """Create the per-process SQLAlchemy engine used for inventory reads."""
    settings.validate_inventory()
    return create_engine(
        build_database_url(settings),
        pool_pre_ping=True,
        pool_recycle=settings.mysql_pool_recycle,
        pool_size=settings.mysql_pool_size,
        max_overflow=settings.mysql_max_overflow,
        future=True,
    )
