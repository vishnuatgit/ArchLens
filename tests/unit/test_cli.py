import pytest
from typer.testing import CliRunner
from unittest.mock import patch
from app.cli import app
from app.exceptions import InvalidRepositoryURLError, RepositoryNotFoundError, RateLimitExceededError

runner = CliRunner()

@pytest.fixture
def mock_async_analyze():
    with patch("app.cli.async_analyze") as mock:
        yield mock

def test_analyze_success(mock_async_analyze):
    mock_async_analyze.return_value = {
        "owner": "test",
        "name": "repo",
        "repo_type": "library",
        "score": 85,
        "duration": 1.2,
        "analysis_id": 1,
        "breakdown": {"documentation": 10, "security": 8},
        "strengths": ["Good docs"],
        "weaknesses": ["Needs more tests"],
        "suggestions": ["Add CI"]
    }
    result = runner.invoke(app, ["https://github.com/test/repo"])
    assert result.exit_code == 0
    assert "Analysis Complete" in result.stdout
    assert "Overall Score: 85/100" in result.stdout
    assert "Good docs" in result.stdout
    assert "Needs more tests" in result.stdout
    assert "Add CI" in result.stdout

def test_analyze_invalid_url(mock_async_analyze):
    mock_async_analyze.side_effect = InvalidRepositoryURLError("not_a_url")
    result = runner.invoke(app, ["not_a_url"])
    assert result.exit_code == 1
    assert "Invalid GitHub repository URL" in result.stdout

def test_analyze_not_found(mock_async_analyze):
    mock_async_analyze.side_effect = RepositoryNotFoundError("a", "b")
    result = runner.invoke(app, ["https://github.com/a/b"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()

def test_analyze_rate_limit(mock_async_analyze):
    mock_async_analyze.side_effect = RateLimitExceededError(reset_epoch=123)
    result = runner.invoke(app, ["https://github.com/a/b"])
    assert result.exit_code == 1
    assert "rate limit exceeded" in result.stdout

def test_analyze_general_error(mock_async_analyze):
    mock_async_analyze.side_effect = Exception("General error")
    result = runner.invoke(app, ["https://github.com/a/b"])
    assert result.exit_code == 1
    assert "An unexpected error occurred" in result.stdout
