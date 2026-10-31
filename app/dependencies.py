"""
FastAPI dependency injection providers.

Centralises service instantiation so that routers receive fully-configured
service instances via `Depends()` rather than importing module-level singletons.
"""

import logging
from datetime import timedelta
from functools import lru_cache

from fastapi import Request

from app.config import settings
from app.services.analysis_service import AnalysisService
from app.services.rate_limiter import SlidingWindowRateLimiter
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.dependencies")


@lru_cache(maxsize=1)
def get_analysis_service() -> AnalysisService:
    """Returns a cached singleton AnalysisService instance."""
    logger.debug("Initialising AnalysisService singleton")
    cache_minutes = settings.ANALYSIS_CACHE_MINUTES
    return AnalysisService(
        cache_ttl=timedelta(minutes=cache_minutes) if cache_minutes > 0 else None,
        rate_limiter=SlidingWindowRateLimiter(
            max_events=settings.ANALYSIS_RATE_LIMIT,
            window_seconds=settings.ANALYSIS_RATE_WINDOW_SECONDS,
        ),
    )


@lru_cache(maxsize=1)
def get_repository_service() -> RepositoryService:
    """Returns a cached singleton RepositoryService instance."""
    logger.debug("Initialising RepositoryService singleton")
    return RepositoryService()


def get_client_ip(request: Request) -> str:
    """
    Identifies the caller for per-client rate limiting.

    Behind a reverse proxy (such as Render's) every request arrives from the proxy,
    so the first X-Forwarded-For entry is used when present. Clients can forge that
    header, which is acceptable for a demo-level limit.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    first_hop = forwarded_for.split(",")[0].strip()
    if first_hop:
        return first_hop
    return request.client.host if request.client else "unknown"
