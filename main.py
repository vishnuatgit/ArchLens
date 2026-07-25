import logging
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.exceptions import (
    AnalysisNotFoundError,
    ArchLensError,
    InvalidRepositoryURLError,
    RateLimitExceededError,
    RepositoryNotFoundError,
)
from app.middleware.logging_middleware import LoggingMiddleware
from app.routers import api, web

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
    description="Repository Intelligence & Engineering Quality Analysis Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register custom logging and timing middleware
app.add_middleware(LoggingMiddleware)

# Mount static files directory
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")

# Register Web and REST API routers
app.include_router(web.router)
app.include_router(api.router)


# Centralised Exception Handlers for JSON API requests
@app.exception_handler(InvalidRepositoryURLError)
async def invalid_url_handler(request: Request, exc: InvalidRepositoryURLError):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": exc.message, "error_code": "INVALID_URL", "status_code": 400},
        )
    raise exc


@app.exception_handler(RepositoryNotFoundError)
async def repo_not_found_handler(request: Request, exc: RepositoryNotFoundError):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": exc.message, "error_code": "REPO_NOT_FOUND", "status_code": 404},
        )
    raise exc


@app.exception_handler(AnalysisNotFoundError)
async def analysis_not_found_handler(request: Request, exc: AnalysisNotFoundError):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": exc.message, "error_code": "ANALYSIS_NOT_FOUND", "status_code": 404},
        )
    raise exc


@app.exception_handler(RateLimitExceededError)
async def rate_limit_handler(request: Request, exc: RateLimitExceededError):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": exc.message, "error_code": "RATE_LIMIT_EXCEEDED", "status_code": 503},
        )
    raise exc


@app.get("/health", tags=["System"])
def health_check():
    """Returns system status and basic application details."""
    logger.info("Health check endpoint accessed")
    return {
        "status": "healthy",
        "app": "ArchLens",
        "version": "1.0.0",
    }

