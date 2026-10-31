"""
The report's check-by-check evidence is rebuilt from what the scorer stored.

These tests run the real MetricsService over hundreds of generated repositories,
store its output the way the database does, and check that the evidence explains
every dimension's points exactly and gets every file check right.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.services import metrics_service as rules
from app.services.evidence import (
    GIVEN_STATUS,
    MISSING,
    PASSED,
    SKIPPED_STATUS,
    UNKNOWN,
    build_evidence,
    build_fix_plan,
    workflow_count,
)
from app.services.metrics_service import (
    DIMENSION_LABELS,
    DIMENSION_MAX_POINTS,
    MetricsService,
    RepoType,
)
from app.services.report_view import DimensionScore, ReportView

scorer = MetricsService()

# Each entry adds one file or folder to the generated repository's root
POOL = {
    "readme": ("README.md", "file"),
    "license": ("LICENSE", "file"),
    "contributing": ("CONTRIBUTING.md", "file"),
    "docs": ("docs", "dir"),
    "tests": ("tests", "dir"),
    "src": ("src", "dir"),
    "gitignore": (".gitignore", "file"),
    "requirements": ("requirements.txt", "file"),
    "env": (".env.example", "file"),
    "security": ("SECURITY.md", "file"),
    "pyproject": ("pyproject.toml", "file"),
    "mypy": ("mypy.ini", "file"),
    "precommit": (".pre-commit-config.yaml", "file"),
    "makefile": ("Makefile", "file"),
}

# Which files make each all-or-nothing check pass
PASSES_WITH = {
    "readme": {"readme"},
    "license": {"license"},
    "contributing": {"contributing", "docs"},
    "tests_dir": {"tests"},
    "source_dir": {"src"},
    "config_files": {"gitignore", "requirements", "env", "pyproject", "mypy", "precommit"},
    "gitignore": {"gitignore"},
    "lockfile": {"requirements"},
    "env_template": {"env"},
    "security_policy": {"security"},
    "linter": {"pyproject"},
    "type_checker": {"mypy"},
    "pre_commit": {"precommit"},
}
# The makefile also counts as project configuration
PASSES_WITH["config_files"] |= {"makefile"}

GIVEN_UNDER = {
    RepoType.PERSONAL: {"workflows", "security_policy", "type_checker", "pre_commit"}
    | {"stars", "forks", "contributors"},
    RepoType.ENTERPRISE: {"stars", "forks", "contributors"},
    RepoType.LIBRARY: set(),
}
SKIPPED_UNDER = {
    RepoType.PERSONAL: {"license", "contributing", "tests_dir"},
    RepoType.ENTERPRISE: set(),
    RepoType.LIBRARY: set(),
}


def stored_report(present: set[str], profile: RepoType, rng: random.Random, workflows: int):
    """Scores a generated repository and returns it as the report page sees it."""
    now = datetime.now(UTC).replace(tzinfo=None)
    days = rng.choice([0, 30, 31, 90, 91, 180, 181, 500, None])
    metadata = {
        "stargazers_count": rng.choice([0, 9, 10, 49, 50, 5000]),
        "forks_count": rng.choice([0, 4, 5, 19, 20, 900]),
        "open_issues_count": rng.choice([0, 1, 10, 11, 300]),
        "size": rng.choice([10, 50_000, 50_001, 200_000, 200_001]),
        "pushed_at": (
            None if days is None else (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ),
    }
    root = [{"name": POOL[key][0], "type": POOL[key][1]} for key in sorted(present)]
    contributors = rng.choice([0, 1, 2, 4, 5, 100])
    commits = [{}] * rng.choice([0, 1, 2, 3, 9, 10, 100])
    result = scorer.calculate_overall_report(
        metadata=metadata,
        languages={"Python": 10},
        root_contents=root,
        contributor_count=contributors,
        recent_commits=commits,
        workflow_contents=[{"name": f"ci{i}.yml"} for i in range(workflows)],
        repo_type=profile.value,
    )
    dimensions = [
        DimensionScore(key, label, result["breakdown"][key], DIMENSION_MAX_POINTS[key])
        for key, label in DIMENSION_LABELS.items()
    ]
    return ReportView(
        id=1,
        owner="o",
        name="r",
        url="https://github.com/o/r",
        repo_type=profile.value,
        is_example=False,
        score=result["overall_score"],
        grade=result["health_grade"],
        summary=result["executive_summary"],
        created_at=now,
        duration=1.0,
        dimensions=dimensions,
        strengths=result["strengths"],
        weaknesses=result["weaknesses"],
        suggestions=result["suggestions"],
        languages={},
        stars=metadata["stargazers_count"],
        forks=metadata["forks_count"],
        open_issues=metadata["open_issues_count"],
        contributor_count=contributors,
        repo_size=metadata["size"],
        language_count=1,
    )


def expected_status(check_key: str, present: set[str], profile: RepoType) -> str | None:
    if check_key in SKIPPED_UNDER[profile]:
        return SKIPPED_STATUS
    if check_key not in PASSES_WITH:
        return None  # banded or workflow checks are covered by the points total
    passed = bool(PASSES_WITH[check_key] & present)
    if passed:
        return PASSED
    return GIVEN_STATUS if check_key in GIVEN_UNDER[profile] else MISSING


@pytest.mark.parametrize("profile", list(RepoType))
def test_evidence_explains_every_dimension_of_generated_repositories(profile):
    rng = random.Random(f"evidence-{profile.value}")
    keys = sorted(POOL)
    cases = [set(), set(keys)] + [{key for key in keys if rng.random() < 0.5} for _ in range(300)]
    for present in cases:
        workflows = rng.choice([0, 0, 1, 3])
        report = stored_report(present, profile, rng, workflows)
        evidence = build_evidence(report)

        for dim in evidence:
            assert dim.verified, (profile, sorted(present), dim.key, dim.checks)
            assert sum(c.earned for c in dim.checks) == dim.points
            for check in dim.checks:
                expected = expected_status(check.key, present, profile)
                if expected is not None:
                    assert check.status == expected, (profile, sorted(present), check)

        assert workflow_count(evidence) == workflows


def test_fix_plan_puts_exact_fixes_first_and_projects_the_score():
    rng = random.Random("plan")
    present = {"readme", "license", "tests", "src", "gitignore"}
    report = stored_report(present, RepoType.LIBRARY, rng, workflows=0)
    plan = build_fix_plan(report, build_evidence(report))

    exact = [fix for fix in plan.fixes if fix.exact]
    rest = [fix for fix in plan.fixes if not fix.exact]
    assert plan.fixes == tuple(exact + rest)
    assert [fix.gain for fix in exact] == sorted((fix.gain for fix in exact), reverse=True)
    assert plan.exact_gain == sum(fix.gain for fix in exact)
    assert plan.projected_score == min(100, report.score + plan.exact_gain)
    assert plan.projected_grade == scorer.compute_health_grade(plan.projected_score)

    # The scorer's own suggestion is shown when it wrote one
    workflow_fix = next(fix for fix in plan.fixes if fix.check_label == "CI workflows")
    assert workflow_fix.action == "Add a GitHub Actions workflow."
    assert workflow_fix.gain == rules.WORKFLOW_POINTS


def test_a_perfect_report_has_nothing_to_fix():
    rng = random.Random("perfect")
    report = stored_report(set(POOL), RepoType.PERSONAL, rng, workflows=1)
    plan = build_fix_plan(report, build_evidence(report))
    assert all(not fix.exact for fix in plan.fixes)


def test_reports_without_matching_findings_are_marked_unverified():
    rng = random.Random("legacy")
    report = stored_report({"readme"}, RepoType.LIBRARY, rng, workflows=0)
    legacy = ReportView(
        **{
            **report.__dict__,
            "strengths": ["Has a README"],
            "weaknesses": ["No LICENSE file detected"],
            "suggestions": ["Add a LICENSE file to define legal usage terms."],
        }
    )
    evidence = build_evidence(legacy)
    assert not any(dim.verified for dim in evidence)
    assert any(check.status == UNKNOWN for dim in evidence for check in dim.checks)
    assert build_fix_plan(legacy, evidence) is None
