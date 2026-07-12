"""Shared test fixtures: a real Postgres-backed DB session for tests that need
to exercise stats.py's query layer, API ownership checks, or WS persistence.

Deliberately separate from the dev database: this reads ``TEST_DATABASE_URL``
(never the app's own ``DATABASE_URL``) and defaults to a distinct ``poker_test``
database on the same local Postgres server used by docker-compose. Each test
runs inside a transaction that's rolled back afterward, so nothing needs to be
dropped between runs — schema is created once per session and left in place.

Tests that need this fixture are skipped if the test DB is unreachable, so
pure-computation tests (test_stats.py's fixture-based unit tests) still run
without any DB.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://poker:poker@localhost:5432/poker_test"
)

from poker_engine.db.base import Base  # noqa: E402


def _ensure_test_database_exists(url: str) -> None:
    """Create the target database (e.g. ``poker_test``) if it doesn't exist yet.

    Connects to the server's default ``postgres`` maintenance database to run
    ``CREATE DATABASE`` — never touches the app's own database.
    """
    from sqlalchemy.engine import make_url

    target = make_url(url)
    admin_url = target.set(database="postgres")
    admin_engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def db_engine():
    try:
        _ensure_test_database_exists(TEST_DATABASE_URL)
        engine = create_engine(TEST_DATABASE_URL, future=True)
        with engine.connect():
            pass
    except Exception as exc:
        pytest.skip(f"Test Postgres not reachable at {TEST_DATABASE_URL}: {exc}")
    import poker_engine.db.models  # noqa: F401  (register all mapped classes)

    Base.metadata.create_all(engine)
    yield engine
    # No drop_all: this is a dedicated test database, safe to leave as-is for
    # faster subsequent runs, and dropping it here risks racing other
    # concurrently-running test sessions against the same DB.


@pytest.fixture()
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection, future=True, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
