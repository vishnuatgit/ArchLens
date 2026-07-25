"""
REST API Router for ArchLens (version v1).

Exposes structured JSON endpoints for automated scans, batch reporting,
and external integrations.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_analysis_service, get_repository_service
from app.exceptions import AnalysisNotFoundError
from app.models.db_models import Analysis
from app.repositories.db import get_db
from app.schemas.schemas import (
    AnalysisDetailResponse,
    AnalyzeApiRequest,
    MetricApiResponse,
    PaginatedAnalysisResponse,
    RepositoryResponse,
    AnalysisSummaryResponse,
)
from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.api")

router = APIRouter(prefix="/api/v1", tags=["REST API v1"])


def build_analysis_detail_response(analysis: Analysis) -> AnalysisDetailResponse:
    """Helper to convert ORM Analysis instance to AnalysisDetailResponse Pydantic schema."""
    metrics_obj = None
    if analysis.metrics:
        m = analysis.metrics
        metrics_obj = MetricApiResponse(
            id=m.id,
            analysis_id=m.analysis_id,
            stars=m.stars,
            forks=m.forks,
            open_issues=m.open_issues,
            language_count=m.language_count,
            contributor_count=m.contributor_count,
            repo_size=m.repo_size,
            last_pushed=m.last_pushed,
            security_score=getattr(m, "security_score", 0) or 0,
            code_quality_score=getattr(m, "code_quality_score", 0) or 0,
            health_grade=getattr(m, "health_grade", "C") or "C",
            executive_summary=getattr(m, "executive_summary", "") or "",
            languages=json.loads(m.languages_json or "{}"),
            score_breakdown=json.loads(m.score_breakdown_json or "{}"),
            strengths=json.loads(m.strengths_json or "[]"),
            weaknesses=json.loads(m.weaknesses_json or "[]"),
            suggestions=json.loads(m.suggestions_json or "[]"),
        )

    return AnalysisDetailResponse(
        id=analysis.id,
        score=analysis.score,
        health_grade=getattr(analysis.metrics, "health_grade", "C") if analysis.metrics else "C",
        executive_summary=getattr(analysis.metrics, "executive_summary", "") if analysis.metrics else "",
        duration=analysis.duration,
        repo_type=analysis.repo_type,
        created_at=analysis.created_at,
        repository=RepositoryResponse.model_validate(analysis.repository),
        metrics=metrics_obj,
    )


@router.post(
    "/analyze",
    response_model=AnalysisDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger Repository Analysis",
    description="Submits a public GitHub repository URL for automated multi-dimensional engineering analysis.",
)
async def analyze_repository(
    payload: AnalyzeApiRequest,
    db: Session = Depends(get_db),
    analysis_svc: AnalysisService = Depends(get_analysis_service),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """Executes a full repository scan and returns the complete analysis report."""
    logger.info(f"API Trigger: Analyzing {payload.url} (Profile: {payload.repo_type})")
    result = await analysis_svc.run(db=db, url=payload.url, repo_type=payload.repo_type)
    analysis = repo_svc.get_analysis_by_id(db, result["analysis_id"])
    if not analysis:
        raise AnalysisNotFoundError(result["analysis_id"])
    return build_analysis_detail_response(analysis)


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisDetailResponse,
    summary="Get Analysis Report Details",
    description="Fetches full metric breakdown and analysis findings for a specific scan ID.",
)
async def get_analysis_by_id(
    analysis_id: int,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """Retrieves an existing analysis by primary key."""
    analysis = repo_svc.get_analysis_by_id(db, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)
    return build_analysis_detail_response(analysis)


@router.get(
    "/analyses",
    response_model=PaginatedAnalysisResponse,
    summary="List Analysis Runs",
    description="Returns a paginated list of historical repository analyses with optional filtering.",
)
async def list_analyses(
    offset: int = Query(0, ge=0, description="Offset pagination index"),
    limit: int = Query(20, ge=1, le=100, description="Page limit size"),
    repo_type: Optional[str] = Query(None, description="Filter by repository profile"),
    min_score: Optional[int] = Query(None, ge=0, le=100, description="Filter by minimum health score"),
    db: Session = Depends(get_db),
):
    """Paginated list query with filtering support."""
    query = db.query(Analysis)
    if repo_type:
        query = query.filter(Analysis.repo_type == repo_type)
    if min_score is not None:
        query = query.filter(Analysis.score >= min_score)

    total = query.count()
    records = query.order_by(Analysis.created_at.desc()).offset(offset).limit(limit).all()

    items = [
        AnalysisSummaryResponse(
            id=r.id,
            score=r.score,
            health_grade=getattr(r.metrics, "health_grade", "C") if r.metrics else "C",
            duration=r.duration,
            repo_type=r.repo_type,
            created_at=r.created_at,
            repo_owner=r.repository.owner,
            repo_name=r.repository.name,
            repo_url=r.repository.url,
        )
        for r in records
    ]

    return PaginatedAnalysisResponse(total=total, offset=offset, limit=limit, items=items)


@router.get(
    "/health",
    summary="API Health Status",
    description="Returns backend API operational status details.",
)
async def api_health_check():
    """Health check endpoint for API consumers."""
    return {"status": "healthy", "service": "ArchLens REST API", "version": "1.0.0"}
