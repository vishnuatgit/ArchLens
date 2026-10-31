import json
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import get_analysis_service, get_client_ip, get_repository_service
from app.exceptions import ArchLensError
from app.models.db_models import Analysis
from app.repositories.db import get_db
from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService
from app.templating import templates

logger = logging.getLogger("ArchLens.web")

router = APIRouter()

# Repositories offered as one-click suggestions under the analysis form
EXAMPLE_REPOS = ["psf/requests", "pallets/flask"]


def render_home(
    request: Request,
    db: Session,
    repo_svc: RepositoryService,
    error: str | None = None,
    status_code: int = 200,
    form_url: str = "",
    form_repo_type: str = "library",
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Renders the home page, optionally re-filling the form after an error."""
    recent_analyses = repo_svc.get_history(db, limit=5, offset=0)
    featured = repo_svc.get_featured_analysis(db)
    featured_breakdown = {}
    if featured and featured.metrics:
        featured_breakdown = json.loads(featured.metrics.score_breakdown_json or "{}")

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "recent_analyses": recent_analyses,
            "featured": featured,
            "featured_breakdown": featured_breakdown,
            "example_repos": EXAMPLE_REPOS,
            "error": error,
            "form_url": form_url,
            "form_repo_type": form_repo_type,
        },
        status_code=status_code,
        headers=headers,
    )


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the home page with a URL input form and the five most recent analyses.
    """
    return render_home(request, db, repo_svc)


@router.get("/analyze", include_in_schema=False)
async def analyze_form_redirect():
    """Sends a reload or bookmark of the form's POST target back to the form."""
    return RedirectResponse(url="/", status_code=303)


@router.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    url: str = Form(...),
    repo_type: str = Form("library"),
    db: Session = Depends(get_db),
    analysis_svc: AnalysisService = Depends(get_analysis_service),
    repo_svc: RepositoryService = Depends(get_repository_service),
    client_ip: str = Depends(get_client_ip),
):
    """
    Receives a submitted repository URL, runs the full analysis pipeline,
    and redirects to the results page on success.
    """
    url = url.strip()
    form = {"form_url": url, "form_repo_type": repo_type}

    if not url:
        return render_home(
            request,
            db,
            repo_svc,
            error="Please enter a GitHub repository URL.",
            status_code=400,
            **form,
        )

    try:
        result = await analysis_svc.run(db=db, url=url, repo_type=repo_type, client_id=client_ip)
        return RedirectResponse(url=f"/analysis/{result['analysis_id']}", status_code=303)

    except ArchLensError as e:
        log = logger.error if e.status_code >= 500 else logger.warning
        log(f"Analysis failed for URL: {url} | {e.error_code} | {e.message}")
        retry_after = e.retry_after_seconds
        return render_home(
            request,
            db,
            repo_svc,
            error=e.message,
            status_code=e.status_code,
            headers={"Retry-After": str(retry_after)} if retry_after else None,
            **form,
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
            request=request,
            name="404.html",
            context={
                "heading": "Analysis not found",
                "message": (
                    "That analysis ID does not exist or may have been removed. "
                    "The live demo's database resets whenever the server restarts."
                ),
            },
            status_code=404,
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
            "is_example": analysis.is_example,
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
    # Clamp hand-edited query strings instead of failing the page
    offset = max(offset, 0)
    limit = min(max(limit, 1), 100)
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
