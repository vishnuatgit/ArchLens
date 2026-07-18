import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.middleware.logging_middleware import LoggingMiddleware
from app.routers import web

# Setup logging configuration based on settings
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ArchLens")

# Resolve template and static directories relative to this file
BASE_DIR = Path(__file__).resolve().parent

# Initialize the main FastAPI application
app = FastAPI(
    title="ArchLens",
    description="Repository Intelligence Platform for Engineering Analysis",
    version="1.0.0",
)

# Register custom logging and timing middleware
app.add_middleware(LoggingMiddleware)

# Mount the static files directory for CSS, JS, and images
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")

# Register web page routes
app.include_router(web.router)


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
