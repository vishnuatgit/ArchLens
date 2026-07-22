import json
import logging
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from app.repositories.db import get_db
from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.web")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()
_repo_svc = RepositoryService()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    """
    Renders the home page with a URL input form and the five most recent analyses.
    """
    recent_analyses = _repo_svc.get_history(db, limit=5, offset=0)
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
):
    """
    Receives a submitted repository URL, runs the full analysis pipeline,
    and redirects to the results page on success.
    """
    url = url.strip()

    if not url:
        recent_analyses = _repo_svc.get_history(db, limit=5, offset=0)
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
        service = AnalysisService()
        result = await service.run(db=db, url=url, repo_type=repo_type)
        return RedirectResponse(
            url=f"/analysis/{result['analysis_id']}", status_code=303
        )

    except ValueError as e:
        logger.warning(f"Invalid URL submitted: {url} | {str(e)}")
        recent_analyses = _repo_svc.get_history(db, limit=5, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={"recent_analyses": recent_analyses, "error": str(e)},
            status_code=400,
        )

    except RuntimeError as e:
        logger.error(f"Analysis failed for URL: {url} | {str(e)}")
        recent_analyses = _repo_svc.get_history(db, limit=5, offset=0)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "recent_analyses": recent_analyses,
                "error": "Analysis failed. This may be a GitHub API rate limit issue. Please try again shortly.",
            },
            status_code=503,
        )


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
async def results(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    """
    Renders the results dashboard for a previously completed analysis.
    """
    analysis = _repo_svc.get_analysis_by_id(db, analysis_id)
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
            "duration": analysis.duration,
            "created_at": analysis.created_at,
            "breakdown": type("Breakdown", (), breakdown)(),
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
    request: Request, offset: int = 0, limit: int = 20, db: Session = Depends(get_db)
):
    """
    Renders the paginated analysis history page.
    """
    analyses = _repo_svc.get_history(db, limit=limit, offset=offset)

    # Count total for pagination display
    from app.models.db_models import Analysis

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
