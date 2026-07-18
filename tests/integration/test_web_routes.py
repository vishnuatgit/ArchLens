"""
Integration tests for ArchLens web routes.

Uses a file-based SQLite test database and patches AnalysisService
so tests run without making real GitHub API calls.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.repositories.db import Base, get_db
from app.models import db_models  # noqa: F401
from app.models.db_models import Repository, Analysis, Metric
from tests.integration.conftest import test_engine, override_get_db

from main import app

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
        suggestions_json=json.dumps(
            ["Add a LICENSE file to define legal usage terms."]
        ),
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
        with patch("app.routers.web.AnalysisService") as MockService:
            instance = MockService.return_value
            instance.run = AsyncMock(return_value={"analysis_id": 1})
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
        with patch("app.routers.web.AnalysisService") as MockService:
            instance = MockService.return_value
            instance.run = AsyncMock(
                side_effect=ValueError("Invalid or unsupported GitHub repository URL")
            )
            response = client.post("/analyze", data={"url": "not-a-github-url"})
        assert response.status_code == 400
        assert b"Invalid" in response.content

    def test_analyze_runtime_error_returns_503(self, client):
        with patch("app.routers.web.AnalysisService") as MockService:
            instance = MockService.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("rate limit"))
            response = client.post(
                "/analyze", data={"url": "https://github.com/octocat/Hello-World"}
            )
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
