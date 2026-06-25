from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# Configure connection arguments, enabling multi-threaded SQLite access
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Initialize the SQLAlchemy Engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args
)

# Configure the session local factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

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
