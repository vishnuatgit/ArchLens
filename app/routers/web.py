import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_analysis_service, get_client_ip, get_repository_service
from app.exceptions import ArchLensError, InvalidRepositoryURLError
from app.models.db_models import Analysis
from app.repositories.db import get_db
from app.services.analysis_service import AnalysisService
from app.services.charts import language_color, radar_chart
from app.services.evidence import build_evidence, build_fix_plan, workflow_count
from app.services.github_service import canonical_github_url, parse_github_url
from app.services.metrics_service import DIMENSION_LABELS, DIMENSION_MAX_POINTS, RepoType
from app.services.report_export import markdown_filename, report_to_markdown
from app.services.report_view import ReportView, build_report_view, describe_comparison
from app.services.repository_service import HISTORY_SORTS, RepositoryService
from app.services.scoring_guide import (
    build_scoring_guide,
    grade_ranges,
    profile_options,
    tier_ranges,
)
from app.templating import templates

logger = logging.getLogger("ArchLens.web")

# HTML pages are documented in the README; /docs lists the JSON API only
router = APIRouter(include_in_schema=False)

# History orderings, as offered in the page's sort menu
HISTORY_SORT_LABELS = {
    "newest": "Newest first",
    "oldest": "Oldest first",
    "score_high": "Highest score",
    "score_low": "Lowest score",
    "name": "Repository name",
}

# Repositories offered as one-click suggestions under the analysis form
EXAMPLE_REPOS = ["psf/requests", "pallets/flask"]

PROFILE_VALUES = [profile.value for profile in RepoType]

# Errors caused by what was typed: only these mark the repository field as invalid
INPUT_ERROR_CODES = {"INVALID_URL", "REPO_NOT_FOUND", "EMPTY_REPOSITORY"}


def _profile_or_default(value: str | None) -> str:
    """Hand-edited query strings fall back to the library profile instead of failing."""
    return value if value in PROFILE_VALUES else RepoType.LIBRARY.value


def _int_or_default(value: str, default: int) -> int:
    """A hand-edited number in a query string falls back to its default instead of a JSON error."""
    try:
        return int(value)
    except ValueError:
        return default


def _retry_headers(retry_after: int | None) -> dict[str, str] | None:
    return {"Retry-After": str(retry_after)} if retry_after else None


def _demo_limits() -> dict[str, int]:
    """The reuse window and per-visitor limit, as the pages describe them."""
    return {
        "cache_minutes": settings.ANALYSIS_CACHE_MINUTES,
        "rate_limit": settings.ANALYSIS_RATE_LIMIT,
        "rate_window_minutes": settings.ANALYSIS_RATE_WINDOW_SECONDS // 60,
    }


def render_home(
    request: Request,
    db: Session,
    repo_svc: RepositoryService,
    error: str | None = None,
    error_code: str | None = None,
    status_code: int = 200,
    form_url: str = "",
    form_repo_type: str = "library",
    headers: dict[str, str] | None = None,
    autostart: bool = False,
) -> HTMLResponse:
    """
    Renders the home page, optionally re-filling the form after an error or from a
    report's "Analyze again" link (which also asks the page to start right away).
    """
    featured = repo_svc.get_featured_analysis(db)
    examples = [build_report_view(a) for a in repo_svc.get_example_analyses(db)]

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "recent_analyses": repo_svc.get_history(db, limit=5, offset=0),
            "featured": build_report_view(featured) if featured else None,
            "examples": examples,
            "example_repos": EXAMPLE_REPOS,
            "error": error,
            "error_code": error_code,
            # A server or quota error is not the visitor's typo; leave the field alone
            "field_invalid": error_code in INPUT_ERROR_CODES,
            "form_url": form_url,
            "form_repo_type": _profile_or_default(form_repo_type),
            "autostart": autostart and bool(form_url),
            "total_reports": repo_svc.count_history(db),
            **_demo_limits(),
        },
        status_code=status_code,
        headers=headers,
    )


def render_analysis_not_found(request: Request) -> HTMLResponse:
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


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    url: str = "",
    repo_type: str = "library",
    autostart: str = "",
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the home page with the analysis form, example reports and recent analyses.
    `?url=owner/repo&repo_type=...` pre-fills the form; `&autostart=1` (a report's
    "Analyze again" link) starts the live analysis as soon as the page loads.
    """
    return render_home(
        request,
        db,
        repo_svc,
        form_url=url.strip()[:300],
        form_repo_type=repo_type,
        autostart=autostart == "1",
    )


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
            error_code="INVALID_URL",
            status_code=400,
            **form,
        )

    try:
        result = await analysis_svc.run(db=db, url=url, repo_type=repo_type, client_id=client_ip)
        return RedirectResponse(url=f"/analysis/{result['analysis_id']}", status_code=303)

    except ArchLensError as e:
        log = logger.error if e.status_code >= 500 else logger.warning
        log(f"Analysis failed for URL: {url} | {e.error_code} | {e.message}")
        return render_home(
            request,
            db,
            repo_svc,
            error=e.message,
            error_code=e.error_code,
            status_code=e.status_code,
            headers=_retry_headers(e.retry_after_seconds),
            **form,
        )


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
def results(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the report for a previously completed analysis.
    """
    analysis = repo_svc.get_analysis_by_id(db, analysis_id)
    if not analysis:
        return render_analysis_not_found(request)

    report = build_report_view(analysis)
    report_url = str(request.url_for("results", analysis_id=report.id))
    latest_url = str(request.url_for("latest_report", owner=report.owner, repo=report.name))
    # The badge shows this report's profile, so the snippet matches the page
    badge_url = (
        str(request.url_for("repo_badge", owner=report.owner, repo=report.name))
        + f"?profile={report.repo_type}"
    )
    evidence = build_evidence(report)

    # A live report can be refreshed once the reuse window has passed; before that,
    # asking again would only return this same report
    age = datetime.now(UTC).replace(tzinfo=None) - report.created_at
    refreshable = report.is_example or age > timedelta(minutes=settings.ANALYSIS_CACHE_MINUTES)

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "report": report,
            "report_url": report_url,
            "markdown": report_to_markdown(report, report_url=report_url),
            "badge_url": badge_url,
            "latest_url": latest_url,
            # The badge links to /repo/... so it keeps pointing at the newest report
            "badge_markdown": f"[![ArchLens score]({badge_url})]({latest_url})",
            "badge_html": (
                f'<a href="{latest_url}"><img src="{badge_url}" alt="ArchLens score"></a>'
            ),
            "evidence": evidence,
            "fix_plan": build_fix_plan(report, evidence),
            "workflows": workflow_count(evidence),
            "radar": radar_chart([(report.full_name, report.dimensions)]),
            "languages": [
                (language, share, language_color(language))
                for language, share in report.languages.items()
            ],
            "timeline": repo_svc.get_repository_timeline(db, analysis.repository_id),
            "refreshable": refreshable,
            # "Analyze again" opens the home page and runs the live pipeline there
            "rerun_url": "/?"
            + urlencode({"url": report.full_name, "repo_type": report.repo_type, "autostart": 1}),
        },
    )


@router.get("/analysis/{analysis_id}/report.md")
def results_markdown(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """Downloads a report as a Markdown file."""
    analysis = repo_svc.get_analysis_by_id(db, analysis_id)
    if not analysis:
        return render_analysis_not_found(request)

    report = build_report_view(analysis)
    body = report_to_markdown(
        report, report_url=str(request.url_for("results", analysis_id=report.id))
    )
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{markdown_filename(report)}"'},
    )


@router.get("/repo/{owner}/{repo}", response_class=HTMLResponse)
def latest_report(
    request: Request,
    owner: str,
    repo: str,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    A stable link to a repository's newest stored report (the README badge links here).
    Report IDs change when the demo database resets; this address does not.
    """
    parsed_owner, parsed_name = parse_github_url(f"{owner}/{repo}")
    analysis = None
    if parsed_owner and parsed_name:
        analysis = repo_svc.get_latest_analysis(db, canonical_github_url(parsed_owner, parsed_name))
    if analysis:
        return RedirectResponse(url=f"/analysis/{analysis.id}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="404.html",
        context={
            "heading": f"No report for {owner}/{repo} yet",
            "message": "ArchLens has no stored analysis of this repository.",
            "analyze_repo": f"{parsed_owner}/{parsed_name}" if parsed_owner else None,
        },
        status_code=404,
    )


def _same_repository(db: Session, repo_svc: RepositoryService, first: str, second: str) -> bool:
    """
    True when two valid inputs name the same repository: GitHub ignores case, and an
    old name of a renamed repository counts as the repository it now points to.
    """
    url_a, url_b = (
        repo_svc.resolve_url(db, canonical_github_url(*parse_github_url(query)))
        for query in (first, second)
    )
    return url_a.lower() == url_b.lower()


@dataclass
class CompareSide:
    """One column of the compare page: a report, or the reason there isn't one."""

    query: str
    report: ReportView | None = None
    error: str | None = None
    error_code: str | None = None
    status_code: int = 200
    retry_after: int | None = None


async def _resolve_compare_side(
    query: str,
    profile: str,
    db: Session,
    analysis_svc: AnalysisService,
    repo_svc: RepositoryService,
    client_ip: str,
) -> CompareSide:
    """
    Finds a report for one side of a comparison. A stored report of the same profile
    is used whatever its age, so comparing known repositories costs no GitHub calls.
    Otherwise a normal analysis runs, with the usual reuse window and rate limit.
    The query has already been validated by the caller.
    """
    owner, name = parse_github_url(query)
    analysis = repo_svc.get_latest_analysis(db, canonical_github_url(owner, name), profile)
    if analysis is None:
        try:
            result = await analysis_svc.run(
                db=db, url=query, repo_type=profile, client_id=client_ip
            )
        except ArchLensError as e:
            logger.warning(f"Compare could not analyze {query} | {e.error_code}")
            return CompareSide(
                query,
                error=e.message,
                error_code=e.error_code,
                status_code=e.status_code,
                retry_after=e.retry_after_seconds,
            )
        analysis = repo_svc.get_analysis_by_id(db, result["analysis_id"])
        if analysis is None:
            return CompareSide(query, error="The analysis could not be loaded.", status_code=500)

    return CompareSide(query, report=build_report_view(analysis))


@router.get("/compare", response_class=HTMLResponse)
async def compare(
    request: Request,
    a: str = "",
    b: str = "",
    profile: str = "library",
    db: Session = Depends(get_db),
    analysis_svc: AnalysisService = Depends(get_analysis_service),
    repo_svc: RepositoryService = Depends(get_repository_service),
    client_ip: str = Depends(get_client_ip),
):
    """
    Shows two repositories side by side. Without a query it shows the compare form.
    """
    a, b = a.strip(), b.strip()
    profile = _profile_or_default(profile)
    # One-click suggestions: neighbouring pairs of example reports (stored, so free to compare)
    example_names = [
        f"{x.repository.owner}/{x.repository.name}" for x in repo_svc.get_example_analyses(db)
    ]
    context = {
        "a": a,
        "b": b,
        "profile": profile,
        "known_repos": repo_svc.list_repository_names(db),
        "stored_reports": repo_svc.list_stored_reports(db),
        "example_pairs": list(zip(example_names, example_names[1:], strict=False))[:2],
        "form_error": None,
        # Which input the error is about ("a" or "b"), so that field is marked invalid
        "failed_side": None,
        "hint": None,
        "sides": [],
        "summary": None,
        "radar": None,
        "fix_plans": [],
    }

    def render(status_code: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="compare.html",
            context=context,
            status_code=status_code,
            headers=headers,
        )

    if not a or not b:
        # An empty form, or one prefilled from a report's "Compare" button
        if a or b:
            context["hint"] = "Add a second repository to compare against."
        return render()

    # Validate both inputs before doing any work, so a typo on one side
    # never spends GitHub quota analyzing the other
    for side, query in (("a", a), ("b", b)):
        if parse_github_url(query) == (None, None):
            error = InvalidRepositoryURLError(query)
            context["form_error"] = error.message
            context["failed_side"] = side
            return render(error.status_code)

    if _same_repository(db, repo_svc, a, b):
        context["form_error"] = "Those are the same repository. Pick two different ones."
        context["failed_side"] = "b"
        return render(400)

    # One side at a time, because both share this request's database session
    sides = [
        await _resolve_compare_side(query, profile, db, analysis_svc, repo_svc, client_ip)
        for query in (a, b)
    ]
    context["sides"] = sides

    left, right = (side.report for side in sides)
    if left and right:
        context["summary"] = describe_comparison(left, right)
        context["radar"] = radar_chart(
            [(left.full_name, left.dimensions), (right.full_name, right.dimensions)]
        )
        context["fix_plans"] = [build_fix_plan(r, build_evidence(r)) for r in (left, right)]
        return render()

    # Same convention as the analyze form: show the message inline with its real status
    failed = next(side for side in sides if side.error)
    if failed.error_code in INPUT_ERROR_CODES:
        context["failed_side"] = "a" if failed is sides[0] else "b"
    return render(failed.status_code, _retry_headers(failed.retry_after))


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    offset: str = "0",
    limit: str = "20",
    q: str = "",
    profile: str = "",
    sort: str = "newest",
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    """
    Renders the paginated analysis history, filtered by repository name and profile.
    """
    # Clamp or ignore hand-edited query strings instead of failing the page
    offset = min(max(_int_or_default(offset, 0), 0), 2**31 - 1)
    limit = min(max(_int_or_default(limit, 20), 1), 100)
    q = q.strip()[:100]
    profile = profile if profile in PROFILE_VALUES else ""
    sort = sort if sort in HISTORY_SORTS else "newest"

    filters = {"search": q or None, "repo_type": profile or None}
    analyses = repo_svc.get_history(db, limit=limit, offset=offset, sort=sort, **filters)

    # Keeps the filters when paging
    query = {"q": q, "profile": profile, "sort": sort if sort != "newest" else ""}
    page_query = urlencode({key: value for key, value in query.items() if value})

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "analyses": analyses,
            "total": repo_svc.count_history(db, **filters),
            "stored_total": db.query(Analysis).count(),
            "offset": offset,
            "limit": limit,
            "q": q,
            "profile": profile,
            "sort": sort,
            "sort_options": HISTORY_SORT_LABELS,
            "page_query": f"&{page_query}" if page_query else "",
            "filtered": bool(q or profile),
        },
    )


@router.get("/scoring", response_class=HTMLResponse)
async def scoring(request: Request, profile: str = "library"):
    """
    Explains every check and its points, generated from the scorer's own constants.
    """
    profile = _profile_or_default(profile)
    return templates.TemplateResponse(
        request=request,
        name="scoring.html",
        context={
            "profile": profile,
            "profile_options": profile_options(),
            "guide": build_scoring_guide(profile),
            "grades": grade_ranges(),
            "tiers": tier_ranges(),
            "total_points": sum(DIMENSION_MAX_POINTS.values()),
            # Shares of the 100 points, for the stacked bar at the top of the page
            "point_shares": [
                (key, DIMENSION_LABELS[key], points) for key, points in DIMENSION_MAX_POINTS.items()
            ],
        },
    )


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    """What ArchLens is, how it is built and where it falls short."""
    return templates.TemplateResponse(request=request, name="about.html", context=_demo_limits())
