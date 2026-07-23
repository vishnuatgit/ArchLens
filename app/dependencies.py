"""
FastAPI dependency injection providers.

Centralises service instantiation so that routers receive fully-configured
service instances via `Depends()` rather than importing module-level singletons.
"""

import logging
from functools import lru_cache

from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.dependencies")


@lru_cache(maxsize=1)
def get_analysis_service() -> AnalysisService:
    """Returns a cached singleton AnalysisService instance."""
    logger.debug("Initialising AnalysisService singleton")
    return AnalysisService()


@lru_cache(maxsize=1)
def get_repository_service() -> RepositoryService:
    """Returns a cached singleton RepositoryService instance."""
    logger.debug("Initialising RepositoryService singleton")
    return RepositoryService()
