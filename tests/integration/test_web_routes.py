"""
Integration tests for ArchLens web routes.

Uses a file-based SQLite test database and patches AnalysisService
so tests run without making real GitHub API calls.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import main
from app.dependencies import get_analysis_service
from app.exceptions import (
    EmptyRepositoryError,
    InvalidRepositoryURLError,
    RateLimitExceededError,
    RepositoryNotFoundError,
    TooManyAnalysesError,
    UpstreamServiceError,
)
from app.models import db_models  # noqa: F401
from app.models.db_models import Analysis, Metric, Repository
from app.repositories.db import Base, get_db
from app.services.analysis_service import AnalysisService
from app.services.evidence import Fix, FixPlan
from app.services.rate_limiter import SlidingWindowRateLimiter
from main import app
from tests.integration.conftest import override_get_db, test_engine

app.dependency_overrides[get_db] = override_get_db
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test for full isolation."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    # Clean up any dependency overrides added during individual tests
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


@pytest.fixture()
def seeded_analysis(db):
    """
    Inserts a complete Repository -> Analysis -> Metric chain
    and returns the Analysis object.
    """
    repo = Repository(
        owner="octocat",
        name="Hello-World",
        url="https://github.com/octocat/Hello-World",
    )
    db.add(repo)
    db.flush()

    analysis = Analysis(
        repository_id=repo.id,
        score=72,
        duration=1.85,
        created_at=datetime(2026, 7, 18, 10, 0, 0),
    )
    db.add(analysis)
    db.flush()

    metric = Metric(
        analysis_id=analysis.id,
        stars=120,
        forks=35,
        open_issues=4,
        language_count=2,
        contributor_count=6,
        repo_size=1024,
        languages_json=json.dumps({"Python": 85.0, "HTML": 15.0}),
        score_breakdown_json=json.dumps(
            {
                "documentation": 16,
                "activity": 18,
                "organization": 14,
                "community": 12,
                "maintainability": 12,
            }
        ),
        strengths_json=json.dumps(["Has a README", "Active in the last 30 days"]),
        weaknesses_json=json.dumps(["No LICENSE file detected"]),
        suggestions_json=json.dumps(["Add a LICENSE file to define legal usage terms."]),
    )
    db.add(metric)
    db.commit()
    db.refresh(analysis)
    return analysis


# ---------------------------------------------------------------------------
# GET / — Home Page
# ---------------------------------------------------------------------------


class TestHomePage:
    def test_home_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_home_contains_form(self, client):
        response = client.get("/")
        assert b"analyze-form" in response.content

    def test_home_shows_recent_scan(self, client, seeded_analysis):
        response = client.get("/")
        assert b"octocat/Hello-World" in response.content

    def test_home_shows_empty_state_when_no_data(self, client):
        response = client.get("/")
        assert b"No analyses yet" in response.content


# ---------------------------------------------------------------------------
# POST /analyze — Analysis Submission
# ---------------------------------------------------------------------------


class TestAnalyzeEndpoint:
    def test_analyze_redirects_on_success(self, client):
        mock_service = AsyncMock(spec=AnalysisService)
        mock_service.run = AsyncMock(return_value={"analysis_id": 1})
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        response = client.post(
            "/analyze",
            data={"url": "https://github.com/octocat/Hello-World"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/analysis/1"

    def test_analyze_empty_url_returns_400(self, client):
        response = client.post("/analyze", data={"url": "   "})
        assert response.status_code == 400
        assert b"Please enter a GitHub repository URL" in response.content

    def test_analyze_invalid_url_returns_400(self, client):
        mock_service = AsyncMock(spec=AnalysisService)
        mock_service.run = AsyncMock(side_effect=InvalidRepositoryURLError("not-a-github-url"))
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        response = client.post("/analyze", data={"url": "not-a-github-url"})
        assert response.status_code == 400
        assert b"Invalid" in response.content

    def test_analyze_rate_limit_returns_503(self, client):
        mock_service = AsyncMock(spec=AnalysisService)
        mock_service.run = AsyncMock(side_effect=RateLimitExceededError())
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        response = client.post("/analyze", data={"url": "https://github.com/octocat/Hello-World"})
        assert response.status_code == 503
        assert b"rate limit" in response.content.lower()


# ---------------------------------------------------------------------------
# GET /analysis/{id} — Results Page
# ---------------------------------------------------------------------------


class TestResultsPage:
    def test_results_page_renders_for_valid_id(self, client, seeded_analysis):
        response = client.get(f"/analysis/{seeded_analysis.id}")
        assert response.status_code == 200
        assert b"octocat/Hello-World" in response.content

    def test_results_page_shows_score(self, client, seeded_analysis):
        response = client.get(f"/analysis/{seeded_analysis.id}")
        assert b"72" in response.content

    def test_results_page_shows_top_fix_near_score(self, client, seeded_analysis):
        fix = Fix("Add a LICENSE file", "License", "community", "Community", 7, True)
        plan = FixPlan(fixes=(fix,), exact_gain=7, projected_score=79, projected_grade="B")
        with patch("app.routers.web.build_fix_plan", return_value=plan):
            html = client.get(f"/analysis/{seeded_analysis.id}").text
        assert "data-top-fix" in html
        assert "Add a LICENSE file" in html.split("data-top-fix")[1].split("</p>")[0]
        assert "+7 points" in html

    def test_results_page_omits_top_fix_without_fixes(self, client, seeded_analysis):
        with patch("app.routers.web.build_fix_plan", return_value=None):
            html = client.get(f"/analysis/{seeded_analysis.id}").text
        assert "data-top-fix" not in html

    def test_results_page_shows_strengths(self, client, seeded_analysis):
        response = client.get(f"/analysis/{seeded_analysis.id}")
        assert b"Has a README" in response.content

    def test_results_page_returns_404_for_missing_id(self, client):
        response = client.get("/analysis/9999")
        assert response.status_code == 404
        assert b"404" in response.content


# ---------------------------------------------------------------------------
# GET /history — History Page
# ---------------------------------------------------------------------------


class TestHistoryPage:
    def test_history_returns_200(self, client):
        response = client.get("/history")
        assert response.status_code == 200

    def test_history_shows_empty_state_when_no_data(self, client):
        response = client.get("/history")
        assert b"No analyses yet" in response.content

    def test_history_shows_seeded_analysis(self, client, seeded_analysis):
        response = client.get("/history")
        assert b"octocat/Hello-World" in response.content
        assert b"72" in response.content


# ---------------------------------------------------------------------------
# GET /health — Health Check
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_payload(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"
        assert data["app"] == "ArchLens"


# ---------------------------------------------------------------------------
# Demo hardening: errors, examples, formatting, quotas
# ---------------------------------------------------------------------------


def _use_service_raising(error):
    mock_service = AsyncMock(spec=AnalysisService)
    mock_service.run = AsyncMock(side_effect=error)
    app.dependency_overrides[get_analysis_service] = lambda: mock_service


def _add_analysis(db, owner="psf", name="requests", score=77, is_example=False, **metric_fields):
    repo = Repository(owner=owner, name=name, url=f"https://github.com/{owner}/{name}")
    db.add(repo)
    db.flush()
    analysis = Analysis(
        repository_id=repo.id,
        score=score,
        duration=1.2,
        repo_type="library",
        is_example=is_example,
        created_at=datetime(2026, 10, 31, 12, 46, 13),
    )
    db.add(analysis)
    db.flush()
    defaults = {
        "stars": 54641,
        "forks": 12089,
        "open_issues": 245,
        "contributor_count": 100,
        "repo_size": 13635,
        "health_grade": "B+",
        "executive_summary": "Example summary.",
        "score_breakdown_json": json.dumps({"documentation": 15, "activity": 9}),
    }
    db.add(Metric(analysis_id=analysis.id, **{**defaults, **metric_fields}))
    db.commit()
    db.refresh(analysis)
    return analysis


class TestErrorPages:
    def test_unknown_page_renders_html_404(self, client):
        response = client.get("/does-not-exist")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
        assert b"Page not found" in response.content

    def test_unknown_api_route_keeps_json_404(self, client):
        response = client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}

    def test_favicon_is_served(self, client):
        assert client.get("/static/favicon.svg").status_code == 200
        response = client.get("/favicon.ico")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")

    def test_get_analyze_redirects_to_form(self, client):
        response = client.get("/analyze")
        assert response.status_code == 303
        assert response.headers["location"] == "/"


class TestAnalyzeErrors:
    @pytest.mark.parametrize(
        ("error", "status_code", "text"),
        [
            (RepositoryNotFoundError("owner", "nope"), 404, b"was not found on GitHub"),
            (EmptyRepositoryError("owner", "empty"), 422, b"is empty"),
            (UpstreamServiceError("HTTP 401"), 502, b"GitHub could not complete the request"),
            (TooManyAnalysesError(5, 600, 120), 429, b"per 10 minutes"),
        ],
    )
    def test_errors_render_inline_with_status(self, client, error, status_code, text):
        _use_service_raising(error)
        response = client.post("/analyze", data={"url": "owner/repo"})
        assert response.status_code == status_code
        assert text in response.content
        assert b'id="form-error"' in response.content

    def test_rate_limit_sets_retry_after(self, client):
        _use_service_raising(TooManyAnalysesError(5, 600, 120))
        response = client.post("/analyze", data={"url": "owner/repo"})
        assert response.headers["retry-after"] == "120"

    def test_form_keeps_typed_value_and_profile_after_error(self, client):
        _use_service_raising(RepositoryNotFoundError("owner", "nope"))
        response = client.post("/analyze", data={"url": "owner/nope", "repo_type": "personal"})
        assert b'value="owner/nope"' in response.content
        assert b'value="personal" selected' in response.content

    def test_unknown_repo_type_is_rejected(self, client):
        app.dependency_overrides[get_analysis_service] = lambda: AnalysisService()
        response = client.post("/analyze", data={"url": "psf/requests", "repo_type": "banana"})
        assert response.status_code == 400
        assert b"Unknown repository profile" in response.content


class TestHomeContent:
    def test_home_has_example_chips_and_no_mock_claims(self, client):
        response = client.get("/")
        assert b'data-repo="psf/requests"' in response.content
        assert b'data-repo="pallets/flask"' in response.content
        assert b"Fully Secure" not in response.content
        assert b"Enterprise-Grade" not in response.content

    def test_home_previews_example_report(self, client, db):
        example = _add_analysis(db, is_example=True)
        response = client.get("/")
        assert f'href="/analysis/{example.id}"'.encode() in response.content
        assert b"Example report" in response.content
        assert b"Analyzed Oct 31, 2026" in response.content

    def test_home_without_reports_explains_instead_of_faking(self, client):
        response = client.get("/")
        assert b"How it works" in response.content


class TestResultsContent:
    def test_example_report_is_labelled_with_its_date(self, client, db):
        example = _add_analysis(db, is_example=True)
        response = client.get(f"/analysis/{example.id}")
        assert b"Example report." in response.content
        assert b"October 31, 2026" in response.content
        assert b"Run a fresh analysis" in response.content

    def test_live_report_has_no_example_banner(self, client, seeded_analysis):
        response = client.get(f"/analysis/{seeded_analysis.id}")
        assert b"Example report." not in response.content

    def test_large_numbers_are_compact_and_contributors_capped(self, client, db):
        analysis = _add_analysis(db)
        response = client.get(f"/analysis/{analysis.id}")
        assert b">54.6k<" in response.content
        assert b">12.1k<" in response.content
        assert b">100+<" in response.content
        assert b"13.3 MB" in response.content

    def test_tier_badge_uses_shared_cutoffs(self, client, db):
        # 75 used to be "Strong" on the badge but "moderate-health" in the summary
        analysis = _add_analysis(db, score=75)
        response = client.get(f"/analysis/{analysis.id}")
        assert b"tier-high" in response.content
        assert b"Strong Codebase" in response.content


class TestHistoryRows:
    def test_whole_row_links_to_report(self, client, seeded_analysis):
        response = client.get("/history")
        assert f'<a href="/analysis/{seeded_analysis.id}" class="history-row">'.encode() in (
            response.content
        )

    def test_out_of_range_pagination_is_clamped(self, client):
        assert client.get("/history?offset=-5&limit=100000").status_code == 200

    @pytest.mark.parametrize(
        "query", ["offset=abc&limit=-x", "offset=99999999999999999999", "limit=1.5"]
    )
    def test_hand_edited_pagination_falls_back_to_a_page(self, client, query):
        response = client.get(f"/history?{query}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.parametrize(
        "path",
        [
            "/analysis/abc",
            "/analysis/99999999999999999999",
            "/analysis/99999999999999999999/report.md",
        ],
    )
    def test_malformed_or_huge_report_id_is_a_not_found_page(self, client, path):
        response = client.get(path)
        assert response.status_code == 404
        assert "text/html" in response.headers["content-type"]


class TestDemoQuotas:
    @pytest.fixture()
    def live_service(self):
        """A real AnalysisService with GitHub stubbed out, a reuse window and a 2-per-window limit."""
        service = AnalysisService(
            cache_ttl=timedelta(minutes=60),
            rate_limiter=SlidingWindowRateLimiter(max_events=2, window_seconds=600),
        )
        github = MagicMock()
        github.fetch_repo_metadata = AsyncMock(return_value={"pushed_at": None})
        github.fetch_languages = AsyncMock(return_value={"Python": 100})
        github.fetch_contributors = AsyncMock(return_value=[])
        github.fetch_contents = AsyncMock(return_value=[])
        github.fetch_recent_commits = AsyncMock(return_value=[])
        service.github = github
        app.dependency_overrides[get_analysis_service] = lambda: service
        return service

    def test_same_repository_is_reused_instead_of_refetched(self, client, live_service):
        first = client.post("/analyze", data={"url": "https://github.com/psf/requests/"})
        second = client.post("/analyze", data={"url": "PSF/Requests.git"})
        assert first.status_code == second.status_code == 303
        assert first.headers["location"] == second.headers["location"]
        assert live_service.github.fetch_repo_metadata.await_count == 1

    def test_per_client_limit_uses_first_forwarded_ip(self, client, live_service):
        headers = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
        for repo in ("owner/one", "owner/two"):
            assert client.post("/analyze", data={"url": repo}, headers=headers).status_code == 303

        limited = client.post("/analyze", data={"url": "owner/three"}, headers=headers)
        assert limited.status_code == 429
        assert b"Please wait about" in limited.content

        other = {"X-Forwarded-For": "198.51.100.2"}
        assert (
            client.post("/analyze", data={"url": "owner/three"}, headers=other).status_code == 303
        )


class TestLifespan:
    def test_lifespan_opens_and_closes_shared_client_and_seeds(self):
        github = get_analysis_service().github
        with patch.object(main, "seed_examples_on_startup") as seed:
            with TestClient(app):
                assert github._client is not None
                assert not github._client.is_closed
            seed.assert_called_once_with(main.SessionLocal)
        assert github._client is None
