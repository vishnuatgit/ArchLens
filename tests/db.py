"""
The database the tests use.

By default every test uses SQLite, so `pytest` needs nothing installed. Set
TEST_DATABASE_URL (for example `postgresql://postgres:postgres@localhost:5432/archlens`)
to run the tests that touch the database against another database. CI does this for PostgreSQL.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import normalize_database_url
from app.models import db_models  # noqa: F401 - registers the models on Base.metadata
from app.repositories.db import Base


def test_database_url(default: str) -> str:
    """TEST_DATABASE_URL when set, otherwise the SQLite URL the test would have used."""
    return normalize_database_url(os.environ.get("TEST_DATABASE_URL") or default)


def make_engine(default_sqlite_url: str) -> Engine:
    url = test_database_url(default_sqlite_url)
    # SQLite needs this because the app serves one request on one thread and tests on another
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def fresh_engine(default_sqlite_url: str = "sqlite://") -> Engine:
    """An engine whose database has all tables, empty."""
    engine = make_engine(default_sqlite_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine
