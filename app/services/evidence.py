"""
Check-by-check evidence for a stored report, and the "what to fix first" plan built from it.

The scorer stores each dimension's points plus the sentences it wrote while checking
(strengths, weaknesses, suggestions). Every sentence belongs to exactly one check, so
the checks listed on the scoring page (app/services/scoring_guide.py) can be matched
back to what the scorer found. A few checks write nothing (the personal profile's
folder checks, a missing environment template); their result is the only combination
of points that makes the dimension add up.

A dimension's evidence is marked `verified` only when the per-check points add up to
the stored dimension score exactly, so the report never shows a breakdown that
disagrees with the score. tests/unit/test_evidence.py runs the real scorer over many
repositories and checks that every dimension is verified and every check is right.
"""

import re
from dataclasses import dataclass, replace
from itertools import combinations

from app.services.metrics_service import (
    COMMIT_BANDS,
    CONTRIBUTOR_BANDS,
    FORK_BANDS,
    OPEN_ISSUE_BANDS,
    PUSH_RECENCY_BANDS,
    REPO_SIZE_BANDS_KB,
    STAR_BANDS,
    MetricsService,
)
from app.services.report_view import ReportView
from app.services.scoring_guide import GIVEN, SKIPPED, GuideCheck, build_scoring_guide

# Statuses shown on the report
PASSED = "passed"  # full points
PARTIAL = "partial"  # some points (banded checks)
MISSING = "missing"  # no points
GIVEN_STATUS = "given"  # full points without checking, under this profile
SKIPPED_STATUS = "skipped"  # not part of this profile
UNKNOWN = "unknown"  # the stored report does not say

FULL = None  # in SIGNALS: the check's full points under the report's profile

# Check key -> (pattern of a sentence the scorer writes, points that sentence means)
SIGNALS: dict[str, tuple[tuple[str, int | None], ...]] = {
    "readme": ((r"Found repository README", FULL), (r"Missing README", 0)),
    "license": ((r"Found LICENSE", FULL), (r"Missing LICENSE", 0)),
    "contributing": (
        (r"Found documentation/contributing", FULL),
        (r"Missing CONTRIBUTING", 0),
    ),
    "commits": (
        (r"High commit activity", COMMIT_BANDS[0].points),
        (r"Moderate commit activity", COMMIT_BANDS[1].points),
        (r"Low commit activity", COMMIT_BANDS[2].points),
        (r"Zero commit activity", 0),
    ),
    "last_push": (
        (r"Repository updated recently \(within", PUSH_RECENCY_BANDS[0].points),
        (r"Repository updated recently \(last pushed", PUSH_RECENCY_BANDS[1].points),
        (r"Repository is becoming inactive", PUSH_RECENCY_BANDS[2].points),
        (r"Repository is stale", 0),
    ),
    "tests_dir": ((r"Found dedicated test suite", FULL), (r"Missing test suite", 0)),
    "source_dir": ((r"Source code organized", FULL), (r"Missing standard source code", 0)),
    "config_files": (
        (r"Found workspace configuration", FULL),
        (r"Missing standard environment configuration", 0),
    ),
    "stars": (
        (r"Strong community interest", STAR_BANDS[0].points),
        (r"Growing community interest", STAR_BANDS[1].points),
        (r"Low community visibility", 0),
    ),
    "forks": (
        (r"High fork count", FORK_BANDS[0].points),
        (r"Moderate fork activity", FORK_BANDS[1].points),
        (r"Low fork count", 0),
    ),
    "contributors": (
        (r"Active contributor base", CONTRIBUTOR_BANDS[0].points),
        (r"Small active contributor group", CONTRIBUTOR_BANDS[1].points),
        (r"Only a single contributor", 0),
    ),
    "workflows": ((r"Found \d+ GitHub Actions workflow", FULL), (r"No GitHub Actions", 0)),
    "open_issues": (
        (r"Zero open issues", OPEN_ISSUE_BANDS[0].points),
        (r"Manageable open issue count", OPEN_ISSUE_BANDS[1].points),
        (r"High open issue count", 0),
    ),
    "repo_size": (
        (r"Repository size is lean", REPO_SIZE_BANDS_KB[0].points),
        (r"Repository size is moderate", REPO_SIZE_BANDS_KB[1].points),
        (r"Repository is large", 0),
    ),
    "gitignore": ((r"Found \.gitignore", FULL), (r"Missing \.gitignore", 0)),
    "lockfile": ((r"Found dependency lockfile", FULL), (r"Missing dependency lockfile", 0)),
    "env_template": ((r"Found environment variable template", FULL),),
    "security_policy": ((r"Found explicit SECURITY", FULL), (r"Missing SECURITY", 0)),
    "linter": ((r"Found linter/formatter", FULL), (r"Missing explicit linter", 0)),
    "type_checker": (
        (r"Found static type checking", FULL),
        (r"Missing explicit static type checker", 0),
    ),
    "pre_commit": ((r"Found \.pre-commit-config", FULL), (r"No pre-commit git hooks", 0)),
}

# Sentences that describe a whole dimension rather than one check
DIMENSION_NOTES = {"community": r"Community metrics bypassed"}

# Check key -> (pattern of the scorer's own suggestion, action shown when it wrote none).
# Checks without an action (forks) are not offered as fixes.
ACTIONS: dict[str, tuple[str | None, str | None]] = {
    "readme": (r"Add a README", "Add a README.md to the root directory."),
    "license": (r"Add a LICENSE", "Add a LICENSE file."),
    "contributing": (r"Create a CONTRIBUTING", "Add a CONTRIBUTING.md file or a docs/ folder."),
    "commits": (
        r"Commit updates periodically",
        f"Commit more often: {COMMIT_BANDS[0].limit} or more commits in 30 days earns full points.",
    ),
    "last_push": (r"Resume", "Push an update to the repository."),
    "tests_dir": (r"Create a tests/", "Create a tests/ directory."),
    "source_dir": (
        None,
        "Keep the code in a folder the scorer recognises: src/, app/, lib/, sources/ or pkg/.",
    ),
    "config_files": (None, "Add project configuration, such as pyproject.toml or a Makefile."),
    "stars": (r"Promote your repository", "Share the project where its users are."),
    "forks": (None, None),
    "contributors": (r"Open issues for good first", "Label a few good first issues."),
    "workflows": (r"Add a GitHub Actions workflow", "Add a GitHub Actions workflow."),
    "open_issues": (
        None,
        f"Triage the backlog: {OPEN_ISSUE_BANDS[1].limit} or fewer open issues and pull "
        "requests earns points.",
    ),
    "repo_size": (r"Clean up large artifacts", "Remove large build artifacts from the history."),
    "gitignore": (r"Add a \.gitignore", "Add a .gitignore file."),
    "lockfile": (r"Commit a dependency lockfile", "Commit a dependency lockfile."),
    "env_template": (None, "Add a .env.example that lists the settings the project needs."),
    "security_policy": (r"Add a SECURITY\.md", "Add a SECURITY.md policy."),
    "linter": (r"Configure a linter", "Configure a linter or formatter."),
    "type_checker": (r"Add static type checking", "Add a type checker configuration."),
    "pre_commit": (r"Add a \.pre-commit-config", "Add a .pre-commit-config.yaml file."),
}


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    detail: str  # what the check looks for
    status: str
    earned: int | None  # None when the stored report does not say
    possible: int
    evidence: str | None  # the scorer's own sentence, when it wrote one
    banded: bool  # partial credit in steps (commits, stars...) rather than all or nothing
    names: tuple[str, ...] = ()  # the files or folders the check looks for

    @property
    def missing_points(self) -> int:
        return self.possible - (self.earned or 0)


@dataclass(frozen=True)
class DimensionEvidence:
    key: str
    label: str
    points: int
    max_points: int
    checks: tuple[CheckResult, ...]
    notes: tuple[str, ...]
    verified: bool  # the per-check points add up to the stored score

    @property
    def scored_checks(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.status != SKIPPED_STATUS)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.scored_checks if c.status in (PASSED, GIVEN_STATUS))


@dataclass(frozen=True)
class Fix:
    action: str
    check_label: str
    dimension_key: str
    dimension_label: str
    gain: int
    exact: bool  # adding the missing file earns exactly `gain`; otherwise "up to"


@dataclass(frozen=True)
class FixPlan:
    fixes: tuple[Fix, ...]
    exact_gain: int  # points the exact fixes add together
    projected_score: int
    projected_grade: str


def _first_match(pattern: str, sentences: list[str]) -> str | None:
    regex = re.compile(pattern)
    return next((s for s in sentences if regex.match(s)), None)


def _match_signal(check: GuideCheck, sentences: list[str]) -> tuple[int, str] | None:
    """The points a check earned and the sentence that says so, if the scorer wrote one."""
    for pattern, points in SIGNALS.get(check.key, ()):
        sentence = _first_match(pattern, sentences)
        if sentence is not None:
            return (check.points if points is FULL else points), sentence
    return None


def _status(earned: int, possible: int) -> str:
    if earned >= possible:
        return PASSED
    return PARTIAL if earned > 0 else MISSING


def _result(check: GuideCheck, status: str, earned: int | None, evidence: str | None):
    return CheckResult(
        key=check.key,
        label=check.label,
        detail=check.detail,
        status=status,
        earned=earned,
        possible=check.points,
        evidence=evidence,
        banded=bool(check.bands),
        names=check.names,
    )


def _resolve_silent(checks: list[GuideCheck], remaining: int) -> set[str] | None:
    """
    Finds which all-or-nothing checks passed when the scorer wrote nothing for them:
    the only subset whose points add up to what is left of the dimension score.
    Returns None when no subset, or more than one, fits.
    """
    if any(check.bands for check in checks):
        return None
    fits = [
        {check.key for check in subset}
        for size in range(len(checks) + 1)
        for subset in combinations(checks, size)
        if sum(check.points for check in subset) == remaining
    ]
    return fits[0] if len(fits) == 1 else None


def _dimension_evidence(dimension, guide_checks, sentences: list[str]) -> DimensionEvidence:
    results: dict[str, CheckResult] = {}
    silent: list[GuideCheck] = []
    for check in guide_checks:
        if check.status == SKIPPED:
            results[check.key] = _result(check, SKIPPED_STATUS, 0, None)
            continue
        signal = _match_signal(check, sentences)
        if signal is not None:
            earned, sentence = signal
            results[check.key] = _result(check, _status(earned, check.points), earned, sentence)
        elif check.status == GIVEN:
            results[check.key] = _result(check, GIVEN_STATUS, check.points, None)
        else:
            silent.append(check)

    known = sum(r.earned for r in results.values() if r.earned is not None)
    passed = _resolve_silent(silent, dimension.points - known) if silent else set()
    for check in silent:
        if passed is None:
            results[check.key] = _result(check, UNKNOWN, None, None)
        else:
            earned = check.points if check.key in passed else 0
            results[check.key] = _result(check, _status(earned, check.points), earned, None)

    checks = tuple(results[check.key] for check in guide_checks)
    verified = all(c.earned is not None for c in checks) and (
        sum(c.earned for c in checks) == dimension.points
    )
    note_pattern = DIMENSION_NOTES.get(dimension.key)
    notes = tuple(s for s in sentences if note_pattern and re.match(note_pattern, s))
    return DimensionEvidence(
        key=dimension.key,
        label=dimension.label,
        points=dimension.points,
        max_points=dimension.max_points,
        checks=checks,
        notes=notes,
        verified=verified,
    )


def build_evidence(report: ReportView) -> list[DimensionEvidence]:
    """The seven dimensions of a report, each with its checks and what the scorer found."""
    sentences = [*report.strengths, *report.weaknesses]
    guide = {dim.key: dim.checks for dim in build_scoring_guide(report.repo_type)}
    evidence = [_dimension_evidence(dim, guide[dim.key], sentences) for dim in report.dimensions]
    # A report none of whose sentences match was written by an older scorer; points
    # alone are not enough to vouch for its check-level detail
    if not any(check.evidence for dim in evidence for check in dim.checks):
        evidence = [replace(dim, verified=False) for dim in evidence]
    return evidence


def build_fix_plan(report: ReportView, evidence: list[DimensionEvidence]) -> FixPlan | None:
    """
    Every check that lost points and has an action, the exact (all-or-nothing) fixes
    first, largest gain first. Returns None unless every dimension is verified, so a
    plan never leaves out a fix the scorer suggested; callers then show the stored
    suggestions as they are.
    """
    if not all(dim.verified for dim in evidence):
        return None

    fixes = []
    for dim in evidence:
        for check in dim.checks:
            if check.status not in (MISSING, PARTIAL) or check.missing_points <= 0:
                continue
            pattern, default_action = ACTIONS.get(check.key, (None, None))
            suggestion = _first_match(pattern, report.suggestions) if pattern else None
            action = suggestion or default_action
            if action is None:
                continue
            fixes.append(
                Fix(
                    action=action,
                    check_label=check.label,
                    dimension_key=dim.key,
                    dimension_label=dim.label,
                    gain=check.missing_points,
                    exact=not check.banded,
                )
            )

    # sorted() is stable, so equal gains keep the report's dimension order
    fixes = sorted(fixes, key=lambda fix: (not fix.exact, -fix.gain))
    exact_gain = sum(fix.gain for fix in fixes if fix.exact)
    projected = min(100, report.score + exact_gain)
    return FixPlan(
        fixes=tuple(fixes),
        exact_gain=exact_gain,
        projected_score=projected,
        projected_grade=MetricsService().compute_health_grade(projected),
    )


def workflow_count(evidence: list[DimensionEvidence]) -> int | None:
    """GitHub Actions workflows found, read from the CI check; None when unknown."""
    for dim in evidence:
        for check in dim.checks:
            if check.key != "workflows":
                continue
            if check.evidence:
                found = re.match(r"Found (\d+)", check.evidence)
                return int(found.group(1)) if found else 0
            # The personal profile awards CI points without a sentence when none exist
            return 0 if check.status in (MISSING, GIVEN_STATUS) else None
    return None
