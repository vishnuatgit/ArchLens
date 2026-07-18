"""
Shared pytest configuration for integration tests.
Creates the in-memory test database schema before the test session starts.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.repositories.db import Base
from app.models import db_models  # noqa: F401 — register all ORM models on Base

TEST_DB_URL = "sqlite:///./test_integration.db"

test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


def pytest_configure(config):
    """
    Create all tables once when pytest starts collecting tests.
    Each test fixture will drop and recreate them for isolation.
    """
    Base.metadata.create_all(bind=test_engine)
