import json
from dataclasses import replace
from datetime import datetime

import pytest

from app.models.db_models import Analysis, Metric, Repository
from app.services.metrics_service import DIMENSION_LABELS, DIMENSION_MAX_POINTS
from app.services.report_export import markdown_filename, report_to_markdown
from app.services.report_view import (
    DimensionScore,
    build_report_view,
    describe_comparison,
)

BREAKDOWN = {
    "documentation": 15,
    "activity": 9,
    "organization": 15,
    "community": 15,
    "maintainability": 11,
    "security": 3,
    "code_quality": 9,
}


def make_analysis(is_example=False, suggestions=("Commit a dependency lockfile.",), **overrides):
    """An unsaved Analysis with its repository and metrics, as the database returns them."""
    metric = Metric(
        stars=54641,
        forks=12089,
        open_issues=245,
        language_count=2,
        contributor_count=100,
        repo_size=13635,
        health_grade="B+",
        executive_summary="This open-source library scored 77/100.",
        languages_json=json.dumps({"Python": 99.4, "Makefile": 0.6}),
        score_breakdown_json=json.dumps(BREAKDOWN),
        strengths_json=json.dumps(["Found repository README."]),
        weaknesses_json=json.dumps(["High open issue count (245)."]),
        suggestions_json=json.dumps(list(suggestions)),
    )
    analysis = Analysis(
        id=7,
        score=77,
        duration=1.162,
        repo_type="library",
        is_example=is_example,
        created_at=datetime(2026, 10, 31, 12, 46, 13),
        repository=Repository(owner="psf", name="requests", url="https://github.com/psf/requests"),
        metrics=metric,
    )
    for key, value in overrides.items():
        setattr(analysis, key, value)
    return analysis


@pytest.fixture
def report():
    return build_report_view(make_analysis())


class TestReportView:
    def test_decodes_the_stored_json(self, report):
        assert report.full_name == "psf/requests"
        assert report.grade == "B+"
        assert report.languages == {"Python": 99.4, "Makefile": 0.6}
        assert [d.key for d in report.dimensions] == list(DIMENSION_LABELS)
        assert report.dimension("security").points == 3
        assert report.dimension("security").max_points == DIMENSION_MAX_POINTS["security"]
        assert report.tier.key == "high"
        assert report.profile_label == "Open-source library"

    def test_contributors_at_the_page_cap_show_a_plus(self, report):
        assert report.contributors_display == "100+"

    def test_percent_is_clamped(self):
        assert DimensionScore("x", "X", 9, 15).percent == 60
        assert DimensionScore("x", "X", 30, 15).percent == 100
        assert DimensionScore("x", "X", 3, 0).percent == 0

    def test_missing_metrics_fall_back_to_empty_values(self):
        view = build_report_view(make_analysis(metrics=None))
        # No stored grade: show the grade the score maps to, never an invented one
        assert view.score == 77
        assert view.grade == "B+"
        assert view.suggestions == []
        assert all(d.points == 0 for d in view.dimensions)

    def test_unknown_profile_is_shown_as_is(self, report):
        assert replace(report, repo_type="legacy").profile_label == "Legacy"


class TestMarkdownExport:
    def test_contains_score_dimensions_and_findings(self, report):
        md = report_to_markdown(report, report_url="https://example.test/analysis/7")
        assert md.startswith("# ArchLens report: psf/requests\n")
        assert "**Score:** 77/100 · **Grade:** B+ · **Tier:** Strong Codebase" in md
        for label in DIMENSION_LABELS.values():
            assert f"| {label} |" in md
        assert "| Security | 3 | 12 |" in md
        assert "| **Total** | **77** | **100** |" in md
        assert "1. Commit a dependency lockfile." in md
        assert "- High open issue count (245)." in md
        assert "- Found repository README." in md
        assert "| 54,641 | 12,089 | 245 | 100+ | 13.3 MB | 2 |" in md
        assert "Languages: Python 99.4%, Makefile 0.6%" in md
        assert md.rstrip().endswith("Full report: https://example.test/analysis/7")

    def test_example_reports_carry_their_capture_date(self):
        md = report_to_markdown(build_report_view(make_analysis(is_example=True)))
        assert "> Example report, captured from live GitHub data on 2026-10-31." in md

    def test_live_reports_have_no_example_note_and_empty_sections_are_left_out(self):
        md = report_to_markdown(build_report_view(make_analysis(suggestions=())))
        assert "Example report" not in md
        assert "## What to fix first" not in md
        assert "Full report:" not in md

    def test_filename(self, report):
        assert markdown_filename(report) == "archlens-psf-requests-2026-10-31.md"


class TestComparisonSummary:
    def test_names_the_leader_and_the_biggest_gap(self, report):
        other = replace(
            report,
            name="flask",
            score=81,
            dimensions=[replace(d, points=d.max_points) for d in report.dimensions],
        )
        assert describe_comparison(report, other) == (
            "psf/flask scores 4 points higher (81 vs 77). "
            "The biggest difference is security: 12 for psf/flask vs 3 for psf/requests, "
            "out of 12."
        )

    def test_identical_reports_are_tied(self, report):
        assert describe_comparison(report, report) == (
            "psf/requests and psf/requests both score 77/100. Every dimension is tied."
        )

    def test_one_point_is_singular(self, report):
        assert "scores 1 point higher" in describe_comparison(report, replace(report, score=76))
