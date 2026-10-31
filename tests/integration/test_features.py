"""
Integration tests for the README badge, Markdown export, compare page,
stable /repo links, and the scoring and About pages.

GitHub is never contacted: the analysis service is replaced with mocks, or with
a real AnalysisService whose GitHub client is stubbed.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.dependencies import get_analysis_service
from app.exceptions import RepositoryNotFoundError, TooManyAnalysesError
from app.models import db_models  # noqa: F401
from app.models.db_models import Analysis, Metric, Repository
from app.repositories.db import Base, get_db
from app.services import metrics_service as rules
from app.services.analysis_service import AnalysisService
from app.services.github_service import GitHubService
from app.services.rate_limiter import SlidingWindowRateLimiter
from app.services.scoring_guide import describe_minimum_bands
from main import app
from tests.integration.conftest import override_get_db, test_engine

app.dependency_overrides[get_db] = override_get_db
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

FULL_BREAKDOWN = {
    "documentation": 15,
    "activity": 9,
    "organization": 15,
    "community": 15,
    "maintainability": 11,
    "security": 3,
    "code_quality": 9,
}


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    app.dependency_overrides.pop(get_analysis_service, None)


@pytest.fixture()
def client():
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def add_analysis(
    db,
    owner="psf",
    name="requests",
    score=77,
    grade="B+",
    repo_type="library",
    is_example=False,
    created_at=datetime(2026, 10, 31, 12, 0, 0),
    breakdown=None,
    suggestions=("Commit a dependency lockfile for reproducible deployments.",),
):
    """Stores a complete analysis, reusing the repository row when it exists."""
    url = f"https://github.com/{owner}/{name}"
    repo = db.query(Repository).filter(Repository.url == url).first()
    if repo is None:
        repo = Repository(owner=owner, name=name, url=url)
        db.add(repo)
        db.flush()
    analysis = Analysis(
        repository_id=repo.id,
        score=score,
        duration=1.2,
        repo_type=repo_type,
        is_example=is_example,
        created_at=created_at,
    )
    db.add(analysis)
    db.flush()
    db.add(
        Metric(
            analysis_id=analysis.id,
            stars=54641,
            forks=12089,
            open_issues=245,
            contributor_count=100,
            repo_size=13635,
            language_count=1,
            health_grade=grade,
            executive_summary=f"Summary for {owner}/{name}.",
            languages_json=json.dumps({"Python": 100.0}),
            score_breakdown_json=json.dumps(breakdown or FULL_BREAKDOWN),
            strengths_json=json.dumps(["Found repository README."]),
            weaknesses_json=json.dumps(["High open issue count (245)."]),
            suggestions_json=json.dumps(list(suggestions)),
        )
    )
    db.commit()
    db.refresh(analysis)
    return analysis


def use_mock_service(**run_kwargs) -> AsyncMock:
    service = AsyncMock(spec=AnalysisService)
    service.run = AsyncMock(**run_kwargs)
    app.dependency_overrides[get_analysis_service] = lambda: service
    return service


# ---------------------------------------------------------------------------
# README badge
# ---------------------------------------------------------------------------


class TestBadge:
    def test_shows_the_latest_stored_grade_and_score(self, client, db):
        add_analysis(db, score=60, grade="C", created_at=datetime(2026, 10, 1))
        add_analysis(db, score=77, grade="B+", created_at=datetime(2026, 10, 31))

        response = client.get("/badge/psf/requests.svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.headers["cache-control"] == "public, max-age=3600"
        assert "B+ · 77/100" in response.text

    def test_lookup_ignores_case(self, client, db):
        add_analysis(db)
        assert "77/100" in client.get("/badge/PSF/Requests.svg").text

    def test_unknown_repository_is_not_analyzed_and_cached_briefly(self, client):
        response = client.get("/badge/someone/unknown.svg")
        assert response.status_code == 200
        assert "not analyzed" in response.text
        assert response.headers["cache-control"] == "public, max-age=300"

    def test_invalid_name_returns_a_400_badge(self, client):
        response = client.get("/badge/-bad-/repo.svg")
        assert response.status_code == 400
        assert "invalid repository" in response.text

    def test_profile_filter(self, client, db):
        add_analysis(db, repo_type="library")
        assert "not analyzed" in client.get("/badge/psf/requests.svg?profile=personal").text
        assert "77/100" in client.get("/badge/psf/requests.svg?profile=library").text

    def test_never_calls_github(self, client, db):
        add_analysis(db)
        use_mock_service(side_effect=AssertionError("the badge must not run an analysis"))
        with patch.object(
            GitHubService, "_make_request", side_effect=AssertionError("GitHub was called")
        ):
            assert client.get("/badge/psf/requests.svg").status_code == 200
            assert client.get("/badge/someone/unknown.svg").status_code == 200


# ---------------------------------------------------------------------------
# Results page additions, Markdown export and stable links
# ---------------------------------------------------------------------------


class TestReportPage:
    def test_offers_badge_snippet_share_link_and_downloads(self, client, db):
        analysis = add_analysis(db)
        html = client.get(f"/analysis/{analysis.id}").text
        # The badge shows the report's own profile, so the snippet matches the page
        assert (
            "[![ArchLens score](http://testserver/badge/psf/requests.svg?profile=library)]"
            "(http://testserver/repo/psf/requests)"
        ) in html
        assert f'data-copy-text="http://testserver/analysis/{analysis.id}"' in html
        assert f'href="/analysis/{analysis.id}/report.md"' in html
        assert "What to fix first" in html
        assert 'href="/scoring?profile=library#security"' in html
        # The Markdown export is embedded so "Copy as Markdown" needs no request
        assert '<textarea id="report-markdown"' in html
        assert "# ArchLens report: psf/requests" in html


class TestMarkdownExport:
    def test_web_download(self, client, db):
        analysis = add_analysis(db)
        response = client.get(f"/analysis/{analysis.id}/report.md")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert response.headers["content-disposition"] == (
            'attachment; filename="archlens-psf-requests-2026-10-31.md"'
        )
        assert response.text.startswith("# ArchLens report: psf/requests")
        assert f"Full report: http://testserver/analysis/{analysis.id}" in response.text

    def test_web_download_for_missing_report_is_an_html_404(self, client):
        response = client.get("/analysis/999/report.md")
        assert response.status_code == 404
        assert b"Analysis not found" in response.content

    def test_api_endpoint(self, client, db):
        analysis = add_analysis(db)
        response = client.get(f"/api/v1/analyses/{analysis.id}/markdown")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "| **Total** | **77** | **100** |" in response.text

    def test_api_endpoint_for_missing_report_is_a_json_404(self, client):
        response = client.get("/api/v1/analyses/999/markdown")
        assert response.status_code == 404
        assert response.json()["error_code"] == "ANALYSIS_NOT_FOUND"


class TestRepoLink:
    def test_redirects_to_the_newest_report(self, client, db):
        add_analysis(db, created_at=datetime(2026, 10, 1))
        newest = add_analysis(db, created_at=datetime(2026, 10, 31))
        response = client.get("/repo/PSF/requests")
        assert response.status_code == 303
        assert response.headers["location"] == f"/analysis/{newest.id}"

    def test_unknown_repository_offers_to_analyze_it(self, client):
        response = client.get("/repo/someone/unknown")
        assert response.status_code == 404
        assert b"No report for someone/unknown yet" in response.content
        # The button opens the home page and starts the live analysis there
        assert b'href="/?url=someone/unknown&amp;autostart=1"' in response.content


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_empty_form(self, client):
        response = client.get("/compare")
        assert response.status_code == 200
        assert b"Compare two repositories" in response.content
        assert b"Pick two repositories" in response.content

    def test_one_repository_prefills_the_form_with_a_hint(self, client):
        response = client.get("/compare?a=psf/requests")
        assert response.status_code == 200
        assert b'value="psf/requests"' in response.content
        assert b"Add a second repository" in response.content

    def test_stored_reports_are_compared_without_running_an_analysis(self, client, db):
        add_analysis(db)
        add_analysis(
            db,
            owner="pallets",
            name="flask",
            score=81,
            grade="A",
            breakdown={**FULL_BREAKDOWN, "security": 7},
        )
        service = use_mock_service()

        response = client.get("/compare?a=psf/requests&b=pallets/flask")
        assert response.status_code == 200
        service.run.assert_not_awaited()
        html = response.text
        assert '<option value="pallets/flask">' in html  # stored repositories are suggested
        assert "pallets/flask scores 4 points higher (81 vs 77)." in html
        assert (
            "The biggest difference is security: 7 for pallets/flask vs 3 for psf/requests, "
            "out of 12."
        ) in html
        assert "−4" in html  # security, A minus B, with a real minus sign

    def test_missing_side_is_analyzed_with_the_client_ip(self, client, db):
        add_analysis(db)
        flask = add_analysis(db, owner="pallets", name="flask", repo_type="personal")
        service = use_mock_service(return_value={"analysis_id": flask.id})

        response = client.get(
            "/compare?a=psf/requests&b=pallets/flask&profile=library",
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
        # The stored flask report has another profile, so it is not used
        service.run.assert_awaited_once()
        kwargs = service.run.await_args.kwargs
        assert kwargs["url"] == "pallets/flask"
        assert kwargs["repo_type"] == "library"
        assert kwargs["client_id"] == "203.0.113.9"
        assert response.status_code == 200

    def test_a_failing_side_is_shown_inline_with_its_status(self, client, db):
        add_analysis(db)
        use_mock_service(side_effect=RepositoryNotFoundError("owner", "nope"))
        response = client.get("/compare?a=psf/requests&b=owner/nope")
        assert response.status_code == 404
        assert b"was not found on GitHub" in response.content
        assert b"psf/requests" in response.content

    def test_rate_limited_side_sets_retry_after(self, client, db):
        add_analysis(db)
        use_mock_service(side_effect=TooManyAnalysesError(5, 600, 120))
        response = client.get("/compare?a=psf/requests&b=owner/new")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "120"

    def test_invalid_input_is_rejected_before_anything_is_analyzed(self, client):
        service = use_mock_service()
        response = client.get("/compare?a=psf/requests&b=not a repo")
        assert response.status_code == 400
        assert b"Invalid or unsupported GitHub repository URL" in response.content
        service.run.assert_not_awaited()

    def test_same_repository_twice_is_rejected(self, client):
        response = client.get("/compare?a=psf/requests&b=https://github.com/PSF/Requests")
        assert response.status_code == 400
        assert b"same repository" in response.content

    def test_new_repositories_follow_the_normal_rate_limit(self, client):
        # A real service with GitHub stubbed: one new analysis allowed per window
        service = AnalysisService(
            cache_ttl=timedelta(minutes=60),
            rate_limiter=SlidingWindowRateLimiter(max_events=1, window_seconds=600),
        )
        github = MagicMock()
        github.fetch_repo_metadata = AsyncMock(return_value={"pushed_at": None})
        github.fetch_languages = AsyncMock(return_value={})
        github.fetch_contributors = AsyncMock(return_value=[])
        github.fetch_contents = AsyncMock(return_value=[])
        github.fetch_recent_commits = AsyncMock(return_value=[])
        service.github = github
        app.dependency_overrides[get_analysis_service] = lambda: service

        response = client.get("/compare?a=owner/one&b=owner/two")
        assert response.status_code == 429
        assert github.fetch_repo_metadata.await_count == 1
        assert b"owner/one" in response.content


# ---------------------------------------------------------------------------
# Scoring and About pages
# ---------------------------------------------------------------------------


class TestScoringPage:
    def test_is_generated_from_the_scoring_constants(self, client):
        html = client.get("/scoring").text
        best_commit_band = describe_minimum_bands(rules.COMMIT_BANDS, "commits")[0][0]
        assert best_commit_band in html
        for label in rules.DIMENSION_LABELS.values():
            assert label in html
        for name in rules.LOCKFILE_NAMES:
            assert f"<code>{name}</code>" in html
        assert 'id="code_quality"' in html

    def test_personal_profile_marks_given_and_skipped_checks(self, client):
        html = client.get("/scoring?profile=personal").text
        assert "not scored" in html
        assert '<span class="status-given">given</span>' in html

    def test_unknown_profile_falls_back_to_library(self, client):
        response = client.get("/scoring?profile=banana")
        assert response.status_code == 200
        assert 'href="/scoring?profile=library" aria-current="page"' in response.text


class TestAboutAndLayout:
    def test_about_page_uses_the_real_settings(self, client):
        html = client.get("/about").text
        assert "Limitations" in html
        assert (
            f"start {settings.ANALYSIS_RATE_LIMIT} new analyses per "
            f"{settings.ANALYSIS_RATE_WINDOW_SECONDS // 60}"
        ) in html
        assert "AnalysisService" in html

    def test_footer_links_to_source_docs_and_author(self, client):
        html = client.get("/").text
        assert 'href="https://github.com/vishnuatgit/ArchLens"' in html
        assert 'href="/docs"' in html
        assert "Built by Vishnu Jayanth" in html
        assert 'href="https://vishnuatgit.github.io"' in html

    def test_home_explains_how_it_works(self, client):
        html = client.get("/").text
        for step in (
            "Fetch repo metadata",
            "Check 7 dimensions",
            "Score and grade",
            "Suggest next steps",
        ):
            assert step in html
