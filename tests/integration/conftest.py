"""
Shared pytest configuration for integration tests.
Creates the in-memory test database schema before the test session starts.
"""

from sqlalchemy.orm import sessionmaker

from app.models import db_models  # noqa: F401 — register all ORM models on Base
from app.repositories.db import Base
from tests.db import make_engine

# SQLite by default; TEST_DATABASE_URL points the whole suite at another database (see tests/db.py)
test_engine = make_engine("sqlite:///./test_integration.db")
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
