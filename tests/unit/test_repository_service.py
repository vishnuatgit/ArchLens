import pytest
from unittest.mock import MagicMock
from app.services.repository_service import RepositoryService
from app.models.db_models import Repository, Analysis, Metric
import json
from datetime import datetime

@pytest.fixture
def repo_service():
    return RepositoryService()

def test_get_or_create_repository_exists(repo_service):
    db = MagicMock()
    existing_repo = Repository(owner="a", name="b", url="url")
    db.query().filter().first.return_value = existing_repo
    
    result = repo_service.get_or_create_repository(db, "a", "b", "url")
    assert result == existing_repo
    db.add.assert_not_called()

def test_get_or_create_repository_new(repo_service):
    db = MagicMock()
    db.query().filter().first.return_value = None
    
    result = repo_service.get_or_create_repository(db, "a", "b", "url")
    assert result.owner == "a"
    assert result.name == "b"
    assert result.url == "url"
    db.add.assert_called_once()

def test_save_analysis(repo_service):
    db = MagicMock()
    report = {
        "security_score": 10,
        "code_quality_score": 10,
        "health_grade": "A",
        "executive_summary": "Good",
        "breakdown": {},
        "strengths": [],
        "weaknesses": [],
        "suggestions": []
    }
    
    analysis_mock = MagicMock()
    analysis_mock.id = 1
    
    # We don't really need to mock the returned object's id if we just check calls,
    # but let's test the return value attributes.
    result = repo_service.save_analysis(
        db=db,
        repository_id=1,
        score=100,
        duration=1.0,
        metadata={"stargazers_count": 10, "pushed_at": "2023-01-01T00:00:00Z"},
        languages={"Python": 100},
        contributor_count=2,
        recent_commits=[],
        report=report,
        repo_type="library"
    )
    
    assert result.repository_id == 1
    assert result.score == 100
    assert db.add.call_count == 2 # Analysis and Metric

def test_get_analysis_by_id(repo_service):
    db = MagicMock()
    repo_service.get_analysis_by_id(db, 1)
    db.query().filter().first.assert_called_once()

def test_get_history(repo_service):
    db = MagicMock()
    repo_service.get_history(db, 10, 0)
    db.query().order_by().offset().limit().all.assert_called_once()
