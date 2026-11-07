from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

# Connection settings per database.
#
# SQLite: opening a connection is a cheap local file open, so every session gets its own and
# nothing is pooled. (A pool of 5 + 10 connections ran dry under about 50 concurrent visitors:
# requests waited 30 seconds for a connection that was only released once the event loop,
# itself blocked waiting for one, could finish the earlier requests. See the load test.)
# check_same_thread is off because a request's session is used from more than one thread.
# PostgreSQL: a real pool, sized for the web server's thread pool, with dead connections
# detected before use.
_in_memory = settings.DATABASE_URL in ("sqlite://", "sqlite:///:memory:")
if settings.DATABASE_URL.startswith("sqlite") and not _in_memory:
    engine_options = {"poolclass": NullPool, "connect_args": {"check_same_thread": False}}
elif _in_memory:
    engine_options = {"connect_args": {"check_same_thread": False}}  # one shared connection
else:
    engine_options = {
        "pool_size": 20,
        "max_overflow": 20,
        "pool_timeout": 15,
        "pool_pre_ping": True,
    }

# Initialize the SQLAlchemy Engine
engine = create_engine(settings.DATABASE_URL, **engine_options)

# Configure the session local factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base class for models to inherit
Base = declarative_base()


def get_db():
    """
    FastAPI dependency that yields a database session.
    Ensures that the connection is closed after a request is completed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
