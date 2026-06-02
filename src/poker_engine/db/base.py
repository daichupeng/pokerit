"""SQLAlchemy engine, session factory, and declarative base.

The connection string comes from ``DATABASE_URL`` and defaults to the Postgres
service defined in ``compose.yaml``. Swapping databases (e.g. to a managed
Postgres for the online launch) is a matter of changing that env var.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://poker:poker@db:5432/poker"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
