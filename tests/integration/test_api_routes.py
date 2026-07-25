"""
Integration tests for ArchLens REST API (v1).

Verifies response schemas, status codes, pagination, and error handling for:
- POST /api/v1/analyze
- GET /api/v1/analyses/{id}
- GET /api/v1/analyses (paginated)
- GET /api/v1/health
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.dependencies import get_analysis_service
from app.exceptions import InvalidRepositoryURLError, RateLimitExceededError
from app.models.db_models import Analysis, Metric, Repository
from app.repositories.db import Base, get_db
from app.services.analysis_service import AnalysisService
from main import app
from tests.integration.conftest import override_get_db, test_engine

app.dependency_overrides[get_db] = override_get_db
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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


@pytest.fixture()
def seeded_analysis(db):
    repo = Repository(
        owner="fastapi",
        name="fastapi",
        url="https://github.com/fastapi/fastapi",
    )
    db.add(repo)
    db.flush()

    analysis = Analysis(
        repository_id=repo.id,
        score=92,
        duration=2.15,
        repo_type="library",
        created_at=datetime(2026, 7, 25, 10, 0, 0),
    )
    db.add(analysis)
    db.flush()

    metric = Metric(
        analysis_id=analysis.id,
        stars=75000,
        forks=6000,
        open_issues=500,
        language_count=3,
        contributor_count=400,
        repo_size=15000,
        security_score=12,
        code_quality_score=13,
        health_grade="A",
        executive_summary="Excellent open-source library with strong security and maintainability.",
        languages_json=json.dumps({"Python": 98.0, "HTML": 2.0}),
        score_breakdown_json=json.dumps(
            {
                "documentation": 15,
                "activity": 15,
                "organization": 15,
                "community": 15,
                "maintainability": 12,
                "security": 12,
                "code_quality": 13,
            }
        ),
        strengths_json=json.dumps(["Found repository README", "Found LICENSE file"]),
        weaknesses_json=json.dumps([]),
        suggestions_json=json.dumps([]),
    )
    db.add(metric)
    db.commit()
    db.refresh(analysis)
    return analysis


class TestApiAnalyze:
    def test_post_analyze_success(self, client, seeded_analysis):
        mock_service = AsyncMock(spec=AnalysisService)
        mock_service.run = AsyncMock(return_value={"analysis_id": seeded_analysis.id})
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        response = client.post(
            "/api/v1/analyze",
            json={"url": "https://github.com/fastapi/fastapi", "repo_type": "library"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == seeded_analysis.id
        assert data["score"] == 92
        assert data["health_grade"] == "A"
        assert data["repository"]["owner"] == "fastapi"
        assert data["metrics"]["security_score"] == 12

    def test_post_analyze_invalid_url_returns_400(self, client):
        mock_service = AsyncMock(spec=AnalysisService)
        mock_service.run = AsyncMock(side_effect=InvalidRepositoryURLError("invalid-url"))
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        response = client.post("/api/v1/analyze", json={"url": "invalid-url"})
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "INVALID_URL"

    def test_post_analyze_rate_limit_returns_503(self, client):
        mock_service = AsyncMock(spec=AnalysisService)
        mock_service.run = AsyncMock(side_effect=RateLimitExceededError())
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        response = client.post(
            "/api/v1/analyze", json={"url": "https://github.com/fastapi/fastapi"}
        )
        assert response.status_code == 503
        data = response.json()
        assert data["error_code"] == "RATE_LIMIT_EXCEEDED"


class TestApiGetAnalysis:
    def test_get_analysis_by_id_success(self, client, seeded_analysis):
        response = client.get(f"/api/v1/analyses/{seeded_analysis.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == seeded_analysis.id
        assert data["score"] == 92
        assert data["health_grade"] == "A"
        assert "executive_summary" in data

    def test_get_analysis_by_id_not_found(self, client):
        response = client.get("/api/v1/analyses/9999")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "ANALYSIS_NOT_FOUND"


class TestApiListAnalyses:
    def test_list_analyses_empty(self, client):
        response = client.get("/api/v1/analyses")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_analyses_with_data(self, client, seeded_analysis):
        response = client.get("/api/v1/analyses?limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["id"] == seeded_analysis.id
        assert item["repo_owner"] == "fastapi"
        assert item["health_grade"] == "A"

    def test_list_analyses_filter_min_score(self, client, seeded_analysis):
        # min_score=95 should filter out our score 92 repo
        response = client.get("/api/v1/analyses?min_score=95")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


class TestApiHealth:
    def test_api_health_check(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ArchLens REST API"
