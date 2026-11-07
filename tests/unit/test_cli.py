import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.exceptions import (
    EmptyRepositoryError,
    InvalidRepositoryURLError,
    RateLimitExceededError,
    RepositoryNotFoundError,
)

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
        "suggestions": ["Add CI"],
    }
    result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
    assert result.exit_code == 0
    assert "Analysis Complete" in result.stdout
    assert "Overall Score: 85/100" in result.stdout
    assert "Good docs" in result.stdout
    assert "Needs more tests" in result.stdout
    assert "Add CI" in result.stdout


def test_analyze_invalid_url(mock_async_analyze):
    mock_async_analyze.side_effect = InvalidRepositoryURLError("not_a_url")
    result = runner.invoke(app, ["analyze", "not_a_url"])
    assert result.exit_code == 1
    assert "Invalid GitHub repository URL" in result.stdout


def test_analyze_not_found(mock_async_analyze):
    mock_async_analyze.side_effect = RepositoryNotFoundError("a", "b")
    result = runner.invoke(app, ["analyze", "https://github.com/a/b"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_analyze_rate_limit(mock_async_analyze):
    mock_async_analyze.side_effect = RateLimitExceededError(reset_epoch=123)
    result = runner.invoke(app, ["analyze", "https://github.com/a/b"])
    assert result.exit_code == 1
    assert "rate limit exceeded" in result.stdout


def test_analyze_general_error(mock_async_analyze):
    mock_async_analyze.side_effect = Exception("General error")
    result = runner.invoke(app, ["analyze", "https://github.com/a/b"])
    assert result.exit_code == 1
    assert "An unexpected error occurred" in result.stdout


def test_analyze_application_error_prints_its_message(mock_async_analyze):
    mock_async_analyze.side_effect = EmptyRepositoryError("a", "b")
    result = runner.invoke(app, ["analyze", "a/b"])
    assert result.exit_code == 1
    assert "is empty" in result.stdout


def test_analyze_is_a_named_subcommand_with_a_profile_option(mock_async_analyze):
    """The documented form, `archlens analyze <url> --profile personal`, parses and runs."""
    mock_async_analyze.return_value = {
        "owner": "a",
        "name": "b",
        "repo_type": "personal",
        "score": 70,
        "duration": 0.5,
        "analysis_id": 2,
        "breakdown": {"documentation": 12},
        "strengths": [],
        "weaknesses": [],
        "suggestions": [],
    }
    result = runner.invoke(app, ["analyze", "https://github.com/a/b", "--profile", "personal"])
    assert result.exit_code == 0, result.stdout
    mock_async_analyze.assert_called_once_with("https://github.com/a/b", "personal")
    assert "Profile: Personal" in result.stdout


def test_help_lists_the_analyze_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_analyze_prints_dependencies_and_vulnerabilities_with_the_fix(mock_async_analyze):
    mock_async_analyze.return_value = {
        "owner": "test",
        "name": "repo",
        "repo_type": "library",
        "score": 85,
        "duration": 1.2,
        "analysis_id": 1,
        "breakdown": {},
        "dependency_scan": {
            "status": "ok",
            "manifests": ["requirements.txt"],
            "dependencies": [
                {
                    "name": "jinja2",
                    "ecosystem": "PyPI",
                    "spec": "==2.1",
                    "version": "2.1",
                    "source": "requirements.txt",
                    "dev": False,
                    "pinned": True,
                }
            ],
            "vulnerability_check": "ok",
            "vulnerabilities": [
                {
                    "id": "GHSA-aaaa",
                    "package": "jinja2",
                    "ecosystem": "PyPI",
                    "version": "2.1",
                    "severity": "high",
                    "summary": "",
                    "fixed": "2.11.3",
                    "aliases": [],
                    "url": "https://osv.dev/vulnerability/GHSA-aaaa",
                }
            ],
            "checked": 1,
            "notes": [],
        },
    }
    result = runner.invoke(app, ["analyze", "test/repo"])
    assert result.exit_code == 0
    assert "1 direct dependencies (1 pinned)" in result.stdout
    assert "GHSA-aaaa" in result.stdout and "upgrade to 2.11.3" in result.stdout
    assert "0-100 score" in result.stdout


def test_analyze_says_when_a_stored_report_was_never_scanned(mock_async_analyze):
    mock_async_analyze.return_value = {
        "owner": "t",
        "name": "r",
        "repo_type": "library",
        "score": 50,
        "duration": 1,
        "analysis_id": 1,
        "breakdown": {},
    }
    assert "not scanned" in runner.invoke(app, ["analyze", "t/r"]).stdout


# ---------------------------------------------------------------------------
# --format, --min-score and --output-dir (used by the GitHub Action)
# ---------------------------------------------------------------------------


@pytest.fixture
def stored_result():
    """The CLI's result for a real stored analysis, with its ReportView."""
    from sqlalchemy.orm import sessionmaker

    from app.services.dependency_service import DependencyScan
    from app.services.report_view import build_report_view
    from tests.db import fresh_engine
    from tests.integration.test_progress_and_pages import add_analysis

    engine = fresh_engine()
    with sessionmaker(bind=engine)() as db:
        analysis = add_analysis(db, score=77)
        scan = DependencyScan(status="ok", vulnerability_check="ok", checked=2)
        analysis.metrics.dependencies_json = json.dumps(scan.to_dict())
        db.commit()
        report = build_report_view(analysis)
    return {
        "owner": "psf",
        "name": "requests",
        "repo_type": "library",
        "score": 77,
        "duration": 1.0,
        "analysis_id": 1,
        "breakdown": {},
        "report": report,
    }


def test_format_json_prints_only_json(mock_async_analyze, stored_result):
    mock_async_analyze.return_value = stored_result
    result = runner.invoke(app, ["analyze", "psf/requests", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert (data["score"], data["grade"], data["repository"]) == (77, "B+", "psf/requests")
    assert data["vulnerability_count"] == 0
    assert data["top_fixes"] and {"action", "gain", "exact"} <= set(data["top_fixes"][0])


def test_format_markdown_prints_the_report_document(mock_async_analyze, stored_result):
    mock_async_analyze.return_value = stored_result
    result = runner.invoke(app, ["analyze", "psf/requests", "-f", "markdown"])
    assert result.exit_code == 0
    assert result.stdout.startswith("# ArchLens report: psf/requests")
    assert "## Known vulnerabilities" in result.stdout


def test_min_score_exit_code_depends_on_the_score(mock_async_analyze, stored_result):
    mock_async_analyze.return_value = stored_result
    above = runner.invoke(app, ["analyze", "psf/requests", "-f", "json", "--min-score", "77"])
    below = runner.invoke(app, ["analyze", "psf/requests", "-f", "json", "--min-score", "78"])
    assert above.exit_code == 0
    assert below.exit_code == 2
    assert json.loads(below.stdout)["score"] == 77  # the report is still printed
    assert "below the minimum of 78" in below.output


def test_min_score_must_be_between_0_and_100(mock_async_analyze):
    assert runner.invoke(app, ["analyze", "a/b", "--min-score", "101"]).exit_code == 2
    mock_async_analyze.assert_not_called()


def test_output_dir_gets_report_summary_and_comment(mock_async_analyze, stored_result, tmp_path):
    mock_async_analyze.return_value = stored_result
    out = tmp_path / "out"
    result = runner.invoke(app, ["analyze", "psf/requests", "-f", "json", "--output-dir", str(out)])
    assert result.exit_code == 0
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# ArchLens report")
    assert json.loads((out / "result.json").read_text(encoding="utf-8"))["score"] == 77
    comment = (out / "comment.md").read_text(encoding="utf-8")
    assert comment.startswith("<!-- archlens-health-comment -->")
    assert "77/100 (B+)" in comment and "Top fixes" in comment


def test_errors_go_to_stderr_in_machine_formats(mock_async_analyze):
    mock_async_analyze.side_effect = RepositoryNotFoundError("a", "b")
    result = runner.invoke(app, ["analyze", "a/b", "--format", "json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()
