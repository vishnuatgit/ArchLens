"""
Unit tests for MetricsService Day 2 features:
- Security score calculation
- Code quality score calculation
- Health grade computation (A+ to F)
- Executive summary generation
- 7-dimension report calculation across repository profiles
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.metrics_service import (
    SCORE_TIERS,
    MetricsService,
    format_capped_count,
    score_tier,
)


@pytest.fixture
def metrics_service():
    return MetricsService()


def test_compute_health_grade(metrics_service):
    assert metrics_service.compute_health_grade(98) == "A+"
    assert metrics_service.compute_health_grade(90) == "A"
    assert metrics_service.compute_health_grade(80) == "B+"
    assert metrics_service.compute_health_grade(70) == "B"
    assert metrics_service.compute_health_grade(55) == "C"
    assert metrics_service.compute_health_grade(40) == "D"
    assert metrics_service.compute_health_grade(20) == "F"


def test_calculate_security_score(metrics_service):
    root_contents = [
        {"name": ".gitignore", "type": "file"},
        {"name": "requirements.txt", "type": "file"},
        {"name": ".env.example", "type": "file"},
        {"name": "SECURITY.md", "type": "file"},
    ]
    score, strengths, weaknesses, suggestions = metrics_service.calculate_security_score(
        root_contents, repo_type="library"
    )
    assert score == 12  # Max score
    assert len(strengths) == 4
    assert len(weaknesses) == 0


def test_calculate_code_quality_score(metrics_service):
    root_contents = [
        {"name": "pyproject.toml", "type": "file"},
        {"name": "mypy.ini", "type": "file"},
        {"name": ".pre-commit-config.yaml", "type": "file"},
    ]
    score, strengths, weaknesses, suggestions = metrics_service.calculate_code_quality_score(
        root_contents, repo_type="library"
    )
    assert score == 13  # Max score
    assert len(strengths) == 3
    assert len(weaknesses) == 0


def test_generate_executive_summary(metrics_service):
    summary = metrics_service.generate_executive_summary(
        score=92,
        grade="A",
        repo_type="library",
        strengths=["Found repository README.", "Active maintenance."],
        weaknesses=["Missing SECURITY.md policy."],
    )
    assert "92/100" in summary
    assert "Grade: A" in summary
    assert "open-source library" in summary
    assert "Primary area for improvement" in summary


def test_calculate_overall_report_7_dimensions(metrics_service):
    report = metrics_service.calculate_overall_report(
        metadata={
            "stargazers_count": 100,
            "forks_count": 25,
            "pushed_at": (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "size": 1000,
        },
        languages={"Python": 1000},
        root_contents=[
            {"name": "README.md", "type": "file"},
            {"name": "LICENSE", "type": "file"},
            {"name": "CONTRIBUTING.md", "type": "file"},
            {"name": ".gitignore", "type": "file"},
            {"name": "requirements.txt", "type": "file"},
            {"name": "pyproject.toml", "type": "file"},
            {"name": "mypy.ini", "type": "file"},
            {"name": ".pre-commit-config.yaml", "type": "file"},
            {"name": "tests", "type": "dir"},
            {"name": "app", "type": "dir"},
        ],
        contributor_count=10,
        recent_commits=[{"sha": "1"} for _ in range(15)],
        workflow_contents=[{"name": "ci.yml"}],
        repo_type="library",
    )

    assert report["overall_score"] >= 95
    assert report["health_grade"] == "A+"
    assert "executive_summary" in report
    assert report["security_score"] == 7  # 3 (.gitignore) + 4 (requirements.txt)
    assert report["code_quality_score"] == 13
    assert len(report["breakdown"]) == 7


def test_executive_summary_builds_clean_sentences(metrics_service):
    summary = metrics_service.generate_executive_summary(
        score=77,
        grade="B+",
        repo_type="library",
        strengths=["Found repository README.", "Found LICENSE permissions file."],
        weaknesses=["High open issue count (245)."],
    )
    assert summary == (
        "This open-source library scored 77/100 (Grade: B+), placing it in the "
        "Strong Codebase tier. Key strengths: found repository README; found LICENSE "
        "permissions file. Primary area for improvement: high open issue count (245)."
    )
    assert ".." not in summary
    assert ". and" not in summary


def test_executive_summary_does_not_invent_strengths(metrics_service):
    summary = metrics_service.generate_executive_summary(
        score=20, grade="F", repo_type="personal", strengths=[], weaknesses=["Missing README."]
    )
    assert "Key strength" not in summary
    assert "personal project" in summary
    assert "Needs Optimization tier" in summary


def test_score_tier_boundaries():
    assert score_tier(100).key == "high"
    assert score_tier(70).key == "high"
    assert score_tier(69).key == "mid"
    assert score_tier(40).key == "mid"
    assert score_tier(39).key == "low"
    assert score_tier(0).key == "low"
    assert [t.min_score for t in SCORE_TIERS] == sorted(
        (t.min_score for t in SCORE_TIERS), reverse=True
    )


def test_summary_tier_matches_results_badge_tier(metrics_service):
    # The summary and the results page badge both come from score_tier()
    for score in (39, 40, 69, 70, 79, 80):
        summary = metrics_service.generate_executive_summary(score, "B", "library", [], [])
        assert f"{score_tier(score).label} tier" in summary


def test_capped_counts_and_thousands_separators(metrics_service):
    assert format_capped_count(100) == "100+"
    assert format_capped_count(42) == "42"

    _, strengths, _, _ = metrics_service.calculate_community_score(
        {"stargazers_count": 54641, "forks_count": 12089},
        contributor_count=100,
        repo_type="library",
    )
    assert "Strong community interest with 54,641 stars." in strengths
    assert "High fork count (12,089)." in strengths
    assert "Active contributor base with 100+ contributors." in strengths
