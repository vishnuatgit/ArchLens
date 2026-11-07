"""
REST API Router for ArchLens (version v1).

Exposes structured JSON endpoints for automated scans, batch reporting,
and external integrations.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import get_analysis_service, get_client_ip, get_repository_service
from app.exceptions import AnalysisNotFoundError, ArchLensError, InvalidRepositoryURLError
from app.models.db_models import Analysis
from app.repositories.db import get_db
from app.schemas.schemas import (
    AnalysisDetailResponse,
    AnalysisSummaryResponse,
    AnalyzeApiRequest,
    ErrorResponse,
    MetricApiResponse,
    PaginatedAnalysisResponse,
    RepositoryResponse,
)
from app.services.analysis_service import AnalysisService
from app.services.github_service import parse_github_url
from app.services.metrics_service import RepoType, grade_for_score
from app.services.report_export import report_to_markdown
from app.services.report_view import build_report_view
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.api")

router = APIRouter(prefix="/api/v1")

NDJSON = "application/x-ndjson"

# What the streaming endpoint sends, one JSON object per line (shown in /docs)
STREAM_EXAMPLE = "\n".join(
    json.dumps(event)
    for event in (
        {"event": "progress", "step": "validate", "status": "done", "repository": "psf/requests"},
        {"event": "progress", "step": "fetch", "status": "running", "completed": 0, "total": 6},
        {
            "event": "progress",
            "step": "fetch",
            "status": "running",
            "call": "languages",
            "completed": 1,
            "total": 6,
        },
        {"event": "progress", "step": "score", "status": "done", "score": 77, "grade": "B+"},
        {"event": "progress", "step": "save", "status": "done", "analysis_id": 4},
        {"event": "done", "analysis_id": 4, "report_url": "/analysis/4", "reused": False},
    )
)


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
            health_grade=m.health_grade or grade_for_score(analysis.score),
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
        health_grade=(analysis.metrics.health_grade if analysis.metrics else None)
        or grade_for_score(analysis.score),
        executive_summary=(
            getattr(analysis.metrics, "executive_summary", "") if analysis.metrics else ""
        ),
        duration=analysis.duration,
        repo_type=analysis.repo_type,
        is_example=analysis.is_example,
        created_at=analysis.created_at,
        repository=RepositoryResponse.model_validate(analysis.repository),
        metrics=metrics_obj,
    )


@router.post(
    "/analyze",
    tags=["Analyses"],
    response_model=AnalysisDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger Repository Analysis",
    description=(
        "Submits a public GitHub repository URL for automated multi-dimensional engineering "
        "analysis. Returns 201 with a new report, or 200 with a report of the same repository "
        "and profile created within the last hour."
    ),
    responses={
        200: {"model": AnalysisDetailResponse, "description": "Recent report reused"},
        400: {"model": ErrorResponse, "description": "Invalid repository URL"},
        404: {"model": ErrorResponse, "description": "Repository not found on GitHub"},
        422: {"description": "Empty repository, or invalid request body"},
        429: {"model": ErrorResponse, "description": "Too many analyses from this client"},
        502: {"model": ErrorResponse, "description": "GitHub returned an error"},
        503: {"model": ErrorResponse, "description": "GitHub API rate limit exhausted"},
    },
)
async def analyze_repository(
    payload: AnalyzeApiRequest,
    response: Response,
    db: Session = Depends(get_db),
    analysis_svc: AnalysisService = Depends(get_analysis_service),
    repo_svc: RepositoryService = Depends(get_repository_service),
    client_ip: str = Depends(get_client_ip),
):
    """Executes a full repository scan and returns the complete analysis report."""
    logger.info(f"API Trigger: Analyzing {payload.url} (Profile: {payload.repo_type})")
    result = await analysis_svc.run(
        db=db, url=payload.url, repo_type=payload.repo_type, client_id=client_ip
    )
    if result.get("reused"):
        response.status_code = status.HTTP_200_OK
    analysis = repo_svc.get_analysis_by_id(db, result["analysis_id"])
    if not analysis:
        raise AnalysisNotFoundError(result["analysis_id"])
    return build_analysis_detail_response(analysis)


async def stream_analysis(
    request: Request,
    payload: AnalyzeApiRequest,
    db: Session,
    analysis_svc: AnalysisService,
    client_ip: str,
) -> AsyncIterator[str]:
    """
    Runs one analysis and yields its progress events as JSON lines, ending with a
    "done" event (with the report's address) or an "error" event (with the same
    message, error code and status the other endpoints use).
    """
    events: asyncio.Queue[dict | None] = asyncio.Queue()

    async def analyze() -> None:
        try:
            result = await analysis_svc.run(
                db=db,
                url=payload.url,
                repo_type=payload.repo_type,
                client_id=client_ip,
                progress=events.put_nowait,
            )
            analysis_id = result["analysis_id"]
            events.put_nowait(
                {
                    "event": "done",
                    "analysis_id": analysis_id,
                    "report_url": request.app.url_path_for("results", analysis_id=analysis_id),
                    "reused": bool(result.get("reused")),
                    "score": result.get("score"),
                }
            )
        except ArchLensError as e:
            log = logger.error if e.status_code >= 500 else logger.warning
            log(f"Streamed analysis failed for {payload.url} | {e.error_code} | {e.message}")
            events.put_nowait(
                {
                    "event": "error",
                    "error": e.message,
                    "error_code": e.error_code,
                    "status_code": e.status_code,
                    "retry_after": e.retry_after_seconds,
                }
            )
        except Exception:
            logger.exception(f"Streamed analysis crashed for {payload.url}")
            events.put_nowait(
                {
                    "event": "error",
                    "error": "Something went wrong on the server. Please try again.",
                    "error_code": "INTERNAL_ERROR",
                    "status_code": 500,
                    "retry_after": None,
                }
            )
        finally:
            events.put_nowait(None)

    task = asyncio.create_task(analyze())
    try:
        while (event := await events.get()) is not None:
            yield json.dumps(event) + "\n"
    finally:
        # Stops the analysis if the browser went away; nothing is stored half-way,
        # because results are only written once scoring has finished
        task.cancel()


@router.post(
    "/analyze/stream",
    tags=["Analyses"],
    response_class=StreamingResponse,
    summary="Analyze a repository, streaming progress",
    description=(
        "Runs the same analysis as `POST /api/v1/analyze` and streams its progress as "
        "newline-delimited JSON, one event per line, so a client can show each step as it "
        "happens: `validate`, `reuse` (a report from the last hour is reused), `fetch` (once per "
        "finished GitHub call, six in all), `analyze`, `score` and `save`. The stream ends with "
        '`{"event": "done", "report_url": ...}` or `{"event": "error", "error_code": ...}`; '
        "errors after the stream starts use the same codes as the other endpoints. "
        "An invalid repository URL is rejected with a 400 before the stream starts. "
        "The home page uses this endpoint for its live progress."
    ),
    responses={
        200: {
            "description": "Progress events, one JSON object per line",
            "content": {NDJSON: {"example": STREAM_EXAMPLE}},
        },
        400: {"model": ErrorResponse, "description": "Invalid repository URL"},
        422: {"description": "Invalid request body (for example an unknown repo_type)"},
    },
)
async def analyze_repository_stream(
    payload: AnalyzeApiRequest,
    request: Request,
    db: Session = Depends(get_db),
    analysis_svc: AnalysisService = Depends(get_analysis_service),
    client_ip: str = Depends(get_client_ip),
):
    """Streams the progress of one analysis as newline-delimited JSON."""
    if parse_github_url(payload.url) == (None, None):
        raise InvalidRepositoryURLError(payload.url)
    logger.info(f"API Stream: Analyzing {payload.url} (Profile: {payload.repo_type})")
    return StreamingResponse(
        stream_analysis(request, payload, db, analysis_svc, client_ip),
        media_type=NDJSON,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/analyses/{analysis_id}",
    tags=["Reports"],
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
    "/analyses/{analysis_id}/markdown",
    tags=["Reports"],
    response_class=PlainTextResponse,
    summary="Export Analysis Report as Markdown",
    description="Returns the report as a Markdown document (text/markdown).",
    responses={
        200: {"content": {"text/markdown": {}}},
        404: {"model": ErrorResponse, "description": "Analysis not found"},
    },
)
async def get_analysis_markdown(
    analysis_id: int,
    request: Request,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """Renders a stored analysis as Markdown."""
    analysis = repo_svc.get_analysis_by_id(db, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)
    report_url = str(request.url_for("results", analysis_id=analysis_id))
    return PlainTextResponse(
        report_to_markdown(build_report_view(analysis), report_url=report_url),
        media_type="text/markdown; charset=utf-8",
    )


@router.get(
    "/analyses",
    tags=["Reports"],
    response_model=PaginatedAnalysisResponse,
    summary="List Analysis Runs",
    description="Returns a paginated list of historical repository analyses with optional filtering.",
)
async def list_analyses(
    offset: int = Query(0, ge=0, le=2**31 - 1, description="Offset pagination index"),
    limit: int = Query(20, ge=1, le=100, description="Page limit size"),
    repo_type: RepoType | None = Query(None, description="Filter by repository profile"),
    min_score: int | None = Query(None, ge=0, le=100, description="Filter by minimum health score"),
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
            health_grade=(r.metrics.health_grade if r.metrics else None)
            or grade_for_score(r.score),
            duration=r.duration,
            repo_type=r.repo_type,
            is_example=r.is_example,
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
    tags=["System"],
    summary="API Health Status",
    description="Returns backend API operational status details.",
)
async def api_health_check():
    """Health check endpoint for API consumers."""
    return {"status": "healthy", "service": "ArchLens REST API", "version": "1.0.0"}
