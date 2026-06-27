import logging
from fastapi import FastAPI
from app.config import settings
from app.middleware.logging_middleware import LoggingMiddleware

# Setup logging configuration based on settings
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ArchLens")

# Initialize the main FastAPI application
app = FastAPI(
    title="ArchLens",
    description="Repository Intelligence Platform for Engineering Analysis",
    version="1.0.0",
)

# Register custom logging and timing middleware
app.add_middleware(LoggingMiddleware)

@app.get("/health", tags=["System"])
def health_check():
    """
    Returns system status and basic application details.
    """
    logger.info("Health check endpoint accessed")
    return {
        "status": "healthy",
        "app": "ArchLens",
        "version": "1.0.0",
    }

@app.get("/", tags=["System"])
def root():
    """
    Temporary root endpoint to verify application execution.
    """
    return {
        "message": "Welcome to ArchLens. Visit /docs for the API documentation."
    }
