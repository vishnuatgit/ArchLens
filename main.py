import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.dependencies import get_analysis_service
from app.exceptions import ArchLensError
from app.middleware.logging_middleware import LoggingMiddleware
from app.repositories.db import SessionLocal
from app.routers import api, web
from app.services.seed_service import seed_examples_on_startup
from app.templating import templates

# Setup logging configuration based on settings
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ArchLens")

# Resolve template and static directories relative to this file
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Opens the shared GitHub HTTP client and loads example reports into an empty database."""
    github = get_analysis_service().github
    github.start()
    if settings.SEED_EXAMPLES:
        seed_examples_on_startup(SessionLocal)
    yield
    await github.aclose()


# Initialize the main FastAPI application
app = FastAPI(
    title="ArchLens",
    description="Repository Intelligence & Engineering Quality Analysis Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register custom logging and timing middleware
app.add_middleware(LoggingMiddleware)

# Mount static files directory
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Register Web and REST API routers
app.include_router(web.router)
app.include_router(api.router)


def is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


# Centralised exception handler: every ArchLensError carries its own status and error code
@app.exception_handler(ArchLensError)
async def archlens_error_handler(request: Request, exc: ArchLensError):
    retry_after = exc.retry_after_seconds
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    if is_api_request(request):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.message,
                "error_code": exc.error_code,
                "status_code": exc.status_code,
            },
            headers=headers,
        )
    return templates.TemplateResponse(
        request=request,
        name="404.html",
        context={
            "status": exc.status_code,
            "heading": "Something went wrong",
            "message": exc.message,
        },
        status_code=exc.status_code,
        headers=headers,
    )


@app.exception_handler(StarletteHTTPException)
async def not_found_page_handler(request: Request, exc: StarletteHTTPException):
    """Serves an HTML 404 page to browsers; API clients keep FastAPI's JSON errors."""
    if exc.status_code == 404 and not is_api_request(request):
        return templates.TemplateResponse(
            request=request, name="404.html", context={}, status_code=404
        )
    return await http_exception_handler(request, exc)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/health", tags=["System"])
def health_check():
    """Returns system status and basic application details."""
    logger.info("Health check endpoint accessed")
    return {
        "status": "healthy",
        "app": "ArchLens",
        "version": "1.0.0",
    }
