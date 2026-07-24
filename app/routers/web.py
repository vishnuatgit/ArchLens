import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dependencies import get_analysis_service, get_repository_service
from app.exceptions import (
    ArchLensError,
    InvalidRepositoryURLError,
    RateLimitExceededError,
    RepositoryNotFoundError,
)
from app.models.db_models import Analysis
from app.repositories.db import get_db
from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.web")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the home page with a URL input form and the five most recent analyses.
    """
    recent_analyses = repo_svc.get_history(db, limit=5, offset=0)
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"recent_analyses": recent_analyses, "error": None},
    )


@router.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    url: str = Form(...),
    repo_type: str = Form("library"),
    db: Session = Depends(get_db),
    analysis_svc: AnalysisService = Depends(get_analysis_service),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Receives a submitted repository URL, runs the full analysis pipeline,
    and redirects to the results page on success.
    """
    url = url.strip()

    if not url:
        recent_analyses = repo_svc.get_history(db, limit=5, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "recent_analyses": recent_analyses,
                "error": "Please enter a GitHub repository URL.",
            },
            status_code=400,
        )

    try:
        result = await analysis_svc.run(db=db, url=url, repo_type=repo_type)
        return RedirectResponse(
            url=f"/analysis/{result['analysis_id']}", status_code=303
        )

    except (InvalidRepositoryURLError, RepositoryNotFoundError) as e:
        logger.warning(f"Invalid URL submitted: {url} | {e.message}")
        recent_analyses = repo_svc.get_history(db, limit=5, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={"recent_analyses": recent_analyses, "error": e.message},
            status_code=400,
        )

    except RateLimitExceededError:
        logger.error(f"Rate limit hit during analysis for URL: {url}")
        recent_analyses = repo_svc.get_history(db, limit=5, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "recent_analyses": recent_analyses,
                "error": "Analysis failed. GitHub API rate limit exceeded. Please try again shortly.",
            },
            status_code=503,
        )

    except ArchLensError as e:
        logger.error(f"Analysis failed for URL: {url} | {e.message}")
        recent_analyses = repo_svc.get_history(db, limit=5, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "recent_analyses": recent_analyses,
                "error": "An unexpected error occurred during analysis. Please try again.",
            },
            status_code=500,
        )


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
async def results(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the results dashboard for a previously completed analysis.
    """
    analysis = repo_svc.get_analysis_by_id(db, analysis_id)
    if not analysis:
        return templates.TemplateResponse(
            request=request, name="404.html", context={}, status_code=404
        )

    metrics = analysis.metrics

    # Deserialize JSON fields stored in the Metric model
    breakdown = json.loads(metrics.score_breakdown_json or "{}")
    strengths = json.loads(metrics.strengths_json or "[]")
    weaknesses = json.loads(metrics.weaknesses_json or "[]")
    suggestions = json.loads(metrics.suggestions_json or "[]")
    languages = json.loads(metrics.languages_json or "{}")

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "owner": analysis.repository.owner,
            "name": analysis.repository.name,
            "repo_type": analysis.repo_type,
            "score": analysis.score,
            "health_grade": getattr(metrics, "health_grade", "C") or "C",
            "executive_summary": getattr(metrics, "executive_summary", "") or "",
            "duration": analysis.duration,
            "created_at": analysis.created_at,
            "breakdown": breakdown,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "suggestions": suggestions,
            "languages": languages,
            "stars": metrics.stars,
            "forks": metrics.forks,
            "open_issues": metrics.open_issues,
            "contributor_count": metrics.contributor_count,
            "repo_size": metrics.repo_size,
            "language_count": metrics.language_count,
        },
    )


@router.get("/history", response_class=HTMLResponse)
async def history(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the paginated analysis history page.
    """
    analyses = repo_svc.get_history(db, limit=limit, offset=offset)

    # Count total for pagination display
    total = db.query(Analysis).count()

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "analyses": analyses,
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    )

