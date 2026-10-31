"""
The "How scoring works" page is generated from the scorer's constants.

These tests run the real MetricsService against the guide, so the page and the
scorer cannot quietly disagree: if someone changes a point value, a threshold or
a profile rule in one place but not the other, a test here fails.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services import metrics_service as rules
from app.services.metrics_service import (
    DIMENSION_MAX_POINTS,
    Band,
    MetricsService,
    RepoType,
    score_tier,
)
from app.services.scoring_guide import (
    GIVEN,
    SKIPPED,
    build_scoring_guide,
    describe_maximum_bands,
    describe_minimum_bands,
    grade_ranges,
    profile_options,
    tier_ranges,
)

PROFILES = list(RepoType)
scorer = MetricsService()


def _file(name: str) -> dict:
    return {"name": name, "type": "file"}


def _dir(name: str) -> dict:
    return {"name": name, "type": "dir"}


def _pushed(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def perfect_repository() -> dict:
    """Passes every check, sitting exactly on the best band's limit everywhere."""
    return {
        "metadata": {
            "stargazers_count": rules.STAR_BANDS[0].limit,
            "forks_count": rules.FORK_BANDS[0].limit,
            "open_issues_count": rules.OPEN_ISSUE_BANDS[0].limit,
            "size": rules.REPO_SIZE_BANDS_KB[0].limit,
            "pushed_at": _pushed(0),
        },
        "languages": {"Python": 1},
        "root_contents": [
            _file("README.md"),
            _file("LICENSE"),
            _file("CONTRIBUTING.md"),
            _dir("tests"),
            _dir("src"),
            _file("pyproject.toml"),
            _file(".gitignore"),
            _file("requirements.txt"),
            _file(".env.example"),
            _file("SECURITY.md"),
            _file("mypy.ini"),
            _file(".pre-commit-config.yaml"),
        ],
        "contributor_count": rules.CONTRIBUTOR_BANDS[0].limit,
        "recent_commits": [{}] * rules.COMMIT_BANDS[0].limit,
        "workflow_contents": [_file("ci.yml")],
    }


def empty_repository() -> dict:
    """Fails every check that is actually measured."""
    return {
        "metadata": {
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": rules.OPEN_ISSUE_BANDS[-1].limit + 1,
            "size": rules.REPO_SIZE_BANDS_KB[-1].limit + 1,
            "pushed_at": None,
        },
        "languages": {},
        "root_contents": [],
        "contributor_count": 0,
        "recent_commits": [],
        "workflow_contents": [],
    }


@pytest.mark.parametrize("profile", PROFILES)
def test_guide_points_add_up_to_each_dimension_maximum(profile):
    guide = build_scoring_guide(profile)
    assert [dim.key for dim in guide] == list(DIMENSION_MAX_POINTS)
    for dim in guide:
        assert dim.max_points == DIMENSION_MAX_POINTS[dim.key]
        assert sum(check.points for check in dim.checks) == dim.max_points, dim.key


@pytest.mark.parametrize("profile", PROFILES)
def test_perfect_repository_scores_exactly_what_the_guide_promises(profile):
    report = scorer.calculate_overall_report(**perfect_repository(), repo_type=profile)
    for dim in build_scoring_guide(profile):
        assert report["breakdown"][dim.key] == sum(c.points for c in dim.checks), dim.key
    assert report["overall_score"] == 100


@pytest.mark.parametrize("profile", PROFILES)
def test_empty_repository_only_gets_the_points_the_guide_marks_as_given(profile):
    report = scorer.calculate_overall_report(**empty_repository(), repo_type=profile)
    for dim in build_scoring_guide(profile):
        given = sum(check.points for check in dim.checks if check.status == GIVEN)
        assert report["breakdown"][dim.key] == given, dim.key


def test_skipped_checks_are_worth_nothing_and_library_skips_nothing():
    for profile in PROFILES:
        for dim in build_scoring_guide(profile):
            for check in dim.checks:
                if check.status == SKIPPED:
                    assert check.points == 0
    library_checks = [c for dim in build_scoring_guide(RepoType.LIBRARY) for c in dim.checks]
    assert all(check.status not in (GIVEN, SKIPPED) for check in library_checks)


# Each helper scores one measurement on its own, with everything else failing
def commit_points(commits: int) -> int:
    return scorer.calculate_activity_score({"pushed_at": None}, [{}] * commits, "library")[0]


def push_points(days_ago: int) -> int:
    return scorer.calculate_activity_score({"pushed_at": _pushed(days_ago)}, [], "library")[0]


def star_points(stars: int) -> int:
    return scorer.calculate_community_score({"stargazers_count": stars}, 0, "library")[0]


def fork_points(forks: int) -> int:
    return scorer.calculate_community_score({"forks_count": forks}, 0, "library")[0]


def contributor_points(contributors: int) -> int:
    return scorer.calculate_community_score({}, contributors, "library")[0]


def open_issue_points(issues: int) -> int:
    metadata = {"open_issues_count": issues, "size": 10**9}
    return scorer.calculate_maintainability_score(metadata, [], "library")[0]


def size_points(size_kb: int) -> int:
    metadata = {"open_issues_count": 10**6, "size": size_kb}
    return scorer.calculate_maintainability_score(metadata, [], "library")[0]


# (bands, measure, direction in which the measured value gets worse)
BAND_CASES = {
    "commits": (rules.COMMIT_BANDS, commit_points, -1),
    "last push": (rules.PUSH_RECENCY_BANDS, push_points, +1),
    "stars": (rules.STAR_BANDS, star_points, -1),
    "forks": (rules.FORK_BANDS, fork_points, -1),
    "contributors": (rules.CONTRIBUTOR_BANDS, contributor_points, -1),
    "open issues": (rules.OPEN_ISSUE_BANDS, open_issue_points, +1),
    "size": (rules.REPO_SIZE_BANDS_KB, size_points, +1),
}


@pytest.mark.parametrize("name", list(BAND_CASES))
def test_scorer_switches_bands_exactly_at_each_limit(name):
    bands, measure, worse = BAND_CASES[name]
    for index, band in enumerate(bands):
        assert measure(band.limit) == band.points
        next_points = bands[index + 1].points if index + 1 < len(bands) else 0
        assert measure(band.limit + worse) == next_points


def test_band_descriptions_read_as_ranges():
    assert describe_minimum_bands((Band(10, 8), Band(3, 4), Band(1, 2)), "commits") == (
        ("≥ 10 commits", 8),
        ("3–9 commits", 4),
        ("1–2 commits", 2),
        ("0 commits", 0),
    )
    assert describe_minimum_bands((Band(50, 5), Band(10, 3)), "stars")[-1] == ("0–9 stars", 0)
    assert describe_maximum_bands((Band(0, 4), Band(10, 2)), "open") == (
        ("0 open", 4),
        ("1–10 open", 2),
        ("> 10 open", 0),
    )
    assert describe_maximum_bands((Band(50_000, 4),), "KB")[0] == ("≤ 50,000 KB", 4)


def test_file_names_on_the_page_come_from_the_scorer():
    security = next(d for d in build_scoring_guide() if d.key == "security")
    lockfile = next(c for c in security.checks if c.label == "Dependency lockfile")
    assert lockfile.names == rules.LOCKFILE_NAMES
    assert lockfile.points == rules.LOCKFILE_POINTS


def test_grade_and_tier_ranges_cover_every_score_once():
    grades = grade_ranges()
    assert grades[0][2] == 100 and grades[-1][1] == 0
    for (_, low, _), (_, _, next_high) in zip(grades, grades[1:], strict=False):
        assert next_high == low - 1
    for grade, low, high in grades:
        assert scorer.compute_health_grade(low) == grade
        assert scorer.compute_health_grade(high) == grade

    for key, _, low, high in tier_ranges():
        assert score_tier(low).key == key
        assert score_tier(high).key == key


def test_profile_options_list_every_profile_with_a_description():
    options = profile_options()
    assert [value for value, _, _ in options] == [p.value for p in RepoType]
    assert all(label and description for _, label, description in options)
