"""
Builds the "How scoring works" page from the scorer's own constants.

Nothing here is a hand-copied number: every point value, threshold and file
name comes from app/services/metrics_service.py. The profile rules (what the
personal and enterprise profiles skip or award without checking) mirror the
MetricsService methods, and tests/unit/test_scoring_guide.py runs the real
scorer to prove the two agree.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.services.metrics_service import (
    API_PAGE_CAP,
    COMMIT_BANDS,
    COMMUNITY_WAIVED_PROFILES,
    CONFIG_FILE_EXTENSIONS,
    CONFIG_FILE_NAMES,
    CONFIG_FILES_POINTS,
    CONTRIBUTING_OR_DOCS_POINTS,
    CONTRIBUTOR_BANDS,
    DIMENSION_LABELS,
    DIMENSION_MAX_POINTS,
    DOCS_DIR_NAMES,
    ENV_TEMPLATE_NAMES,
    ENV_TEMPLATE_POINTS,
    FORK_BANDS,
    GITIGNORE_POINTS,
    GRADE_SCALE,
    LICENSE_POINTS,
    LINTER_CONFIG_NAMES,
    LINTER_CONFIG_POINTS,
    LINTER_CONFIG_PREFIXES,
    LOCKFILE_NAMES,
    LOCKFILE_POINTS,
    OPEN_ISSUE_BANDS,
    PERSONAL_CONFIG_FILES_POINTS,
    PERSONAL_README_POINTS,
    PERSONAL_SOURCE_DIR_POINTS,
    PRE_COMMIT_CONFIG_NAMES,
    PRE_COMMIT_POINTS,
    PROFILE_LABELS,
    PUSH_RECENCY_BANDS,
    README_POINTS,
    REPO_SIZE_BANDS_KB,
    SCORE_TIERS,
    SECURITY_POLICY_POINTS,
    SOURCE_DIR_NAMES,
    SOURCE_DIR_POINTS,
    STAR_BANDS,
    TEST_DIR_NAMES,
    TESTS_DIR_POINTS,
    TYPE_CHECKER_CONFIG_NAMES,
    TYPE_CHECKER_POINTS,
    WORKFLOW_POINTS,
    Band,
    RepoType,
)

# How a check applies under the selected profile
SCORED = "scored"  # measured; points depend on what is found
GIVEN = "given"  # not measured; full points are awarded anyway
SKIPPED = "skipped"  # not part of this profile's score

PROFILE_DESCRIPTIONS = {
    RepoType.LIBRARY: "Every check counts. Use it for projects other people depend on.",
    RepoType.PERSONAL: (
        "Leaves out what mostly matters for shared projects: the license, contributing "
        "guide and test folder are not scored, and community, CI, security policy, type "
        "checker and pre-commit points are awarded without checking."
    ),
    RepoType.ENTERPRISE: (
        "Same as the library profile, except popularity (stars, forks, contributors) is "
        "awarded without checking, since internal apps rarely have public communities."
    ),
}


@dataclass(frozen=True)
class GuideCheck:
    """One row on the scoring page: what is checked and what it is worth."""

    label: str
    detail: str
    points: int  # the most this check can add under the selected profile
    status: str = SCORED
    names: tuple[str, ...] = ()  # file or folder names it looks for
    bands: tuple[tuple[str, int], ...] = ()  # partial credit: (condition, points)
    key: str = ""  # stable identifier, shared with the report's evidence (app/services/evidence.py)


@dataclass(frozen=True)
class GuideDimension:
    key: str
    label: str
    max_points: int
    question: str
    checks: tuple[GuideCheck, ...]


def _number(value: int) -> str:
    return f"{value:,}"


def describe_minimum_bands(bands: tuple[Band, ...], unit: str) -> tuple[tuple[str, int], ...]:
    """Turns 'at least N' bands into readable rows, e.g. ('≥ 10 commits', 8), ('3–9 commits', 4)."""
    rows = []
    for index, band in enumerate(bands):
        if index == 0:
            condition = f"≥ {_number(band.limit)}"
        else:
            upper = bands[index - 1].limit - 1
            condition = (
                _number(band.limit)
                if band.limit == upper
                else f"{_number(band.limit)}–{_number(upper)}"
            )
        rows.append((f"{condition} {unit}", band.points))
    lowest = bands[-1].limit - 1
    remainder = "0" if lowest == 0 else f"0–{_number(lowest)}"
    rows.append((f"{remainder} {unit}", 0))
    return tuple(rows)


def describe_maximum_bands(bands: tuple[Band, ...], unit: str) -> tuple[tuple[str, int], ...]:
    """Turns 'at most N' bands into readable rows, e.g. ('≤ 30 days', 7), ('31–90 days', 4)."""
    rows = []
    for index, band in enumerate(bands):
        if index == 0:
            condition = "0" if band.limit == 0 else f"≤ {_number(band.limit)}"
        else:
            lower = bands[index - 1].limit + 1
            condition = f"{_number(lower)}–{_number(band.limit)}"
        rows.append((f"{condition} {unit}", band.points))
    rows.append((f"> {_number(bands[-1].limit)} {unit}", 0))
    return tuple(rows)


def _best(bands: tuple[Band, ...]) -> int:
    return max(band.points for band in bands)


def _skipped(check: GuideCheck) -> GuideCheck:
    return replace(check, points=0, status=SKIPPED)


def _given(check: GuideCheck) -> GuideCheck:
    return replace(check, status=GIVEN)


def _documentation(profile: RepoType) -> tuple[GuideCheck, ...]:
    personal = profile == RepoType.PERSONAL
    readme = GuideCheck(
        "README",
        "A file whose name starts with README in the root directory.",
        PERSONAL_README_POINTS if personal else README_POINTS,
        names=("README*",),
        key="readme",
    )
    license_ = GuideCheck(
        "License",
        "A LICENSE file (or COPYING) in the root directory.",
        LICENSE_POINTS,
        names=("LICENSE*", "COPYING"),
        key="license",
    )
    guide = GuideCheck(
        "Contributing guide or docs",
        "A CONTRIBUTING file, or a documentation folder.",
        CONTRIBUTING_OR_DOCS_POINTS,
        names=("CONTRIBUTING*", *(f"{name}/" for name in DOCS_DIR_NAMES)),
        key="contributing",
    )
    if personal:
        return readme, _skipped(license_), _skipped(guide)
    return readme, license_, guide


def _activity(profile: RepoType) -> tuple[GuideCheck, ...]:
    commits = GuideCheck(
        "Recent commits",
        f"Commits in the last 30 days, read from one page of results (so at most "
        f"{API_PAGE_CAP} are counted).",
        _best(COMMIT_BANDS),
        bands=describe_minimum_bands(COMMIT_BANDS, "commits"),
        key="commits",
    )
    push = GuideCheck(
        "Last push",
        "Days since anything was last pushed to the repository.",
        _best(PUSH_RECENCY_BANDS),
        bands=describe_maximum_bands(PUSH_RECENCY_BANDS, "days ago"),
        key="last_push",
    )
    return commits, push


def _organization(profile: RepoType) -> tuple[GuideCheck, ...]:
    personal = profile == RepoType.PERSONAL
    tests = GuideCheck(
        "Test folder",
        "A dedicated test directory in the root.",
        TESTS_DIR_POINTS,
        names=tuple(f"{name}/" for name in TEST_DIR_NAMES),
        key="tests_dir",
    )
    source = GuideCheck(
        "Source folder",
        "Code kept in a dedicated directory instead of the root.",
        PERSONAL_SOURCE_DIR_POINTS if personal else SOURCE_DIR_POINTS,
        names=tuple(f"{name}/" for name in SOURCE_DIR_NAMES),
        key="source_dir",
    )
    configs = GuideCheck(
        "Project configuration",
        "Any dotfile, build file or config file in the root.",
        PERSONAL_CONFIG_FILES_POINTS if personal else CONFIG_FILES_POINTS,
        names=(".*", *CONFIG_FILE_NAMES, *(f"*{ext}" for ext in CONFIG_FILE_EXTENSIONS)),
        key="config_files",
    )
    if personal:
        return _skipped(tests), source, configs
    return tests, source, configs


def _community(profile: RepoType) -> tuple[GuideCheck, ...]:
    checks = (
        GuideCheck(
            "Stars",
            "Stargazers on GitHub.",
            _best(STAR_BANDS),
            bands=describe_minimum_bands(STAR_BANDS, "stars"),
            key="stars",
        ),
        GuideCheck(
            "Forks",
            "Forks on GitHub.",
            _best(FORK_BANDS),
            bands=describe_minimum_bands(FORK_BANDS, "forks"),
            key="forks",
        ),
        GuideCheck(
            "Contributors",
            f"People with commits, read from one page of results (at most {API_PAGE_CAP}).",
            _best(CONTRIBUTOR_BANDS),
            bands=describe_minimum_bands(CONTRIBUTOR_BANDS, "contributors"),
            key="contributors",
        ),
    )
    if profile in COMMUNITY_WAIVED_PROFILES:
        return tuple(_given(check) for check in checks)
    return checks


def _maintainability(profile: RepoType) -> tuple[GuideCheck, ...]:
    workflows = GuideCheck(
        "CI workflows",
        "At least one GitHub Actions workflow file.",
        WORKFLOW_POINTS,
        names=(".github/workflows/*",),
        key="workflows",
    )
    issues = GuideCheck(
        "Open issues",
        "Open issues and pull requests, as GitHub counts them.",
        _best(OPEN_ISSUE_BANDS),
        bands=describe_maximum_bands(OPEN_ISSUE_BANDS, "open"),
        key="open_issues",
    )
    size = GuideCheck(
        "Repository size",
        "Size on disk as reported by GitHub, including history.",
        _best(REPO_SIZE_BANDS_KB),
        bands=describe_maximum_bands(REPO_SIZE_BANDS_KB, "KB"),
        key="repo_size",
    )
    if profile == RepoType.PERSONAL:
        return _given(workflows), issues, size
    return workflows, issues, size


def _security(profile: RepoType) -> tuple[GuideCheck, ...]:
    policy = GuideCheck(
        "Security policy",
        "A SECURITY file explaining how to report vulnerabilities.",
        SECURITY_POLICY_POINTS,
        names=("SECURITY*",),
        key="security_policy",
    )
    return (
        GuideCheck(
            ".gitignore",
            "Keeps local secrets and build output out of the repository.",
            GITIGNORE_POINTS,
            names=(".gitignore",),
            key="gitignore",
        ),
        GuideCheck(
            "Dependency lockfile",
            "Pinned dependencies make builds reproducible.",
            LOCKFILE_POINTS,
            names=LOCKFILE_NAMES,
            key="lockfile",
        ),
        GuideCheck(
            "Environment template",
            "Documents required settings without committing real values.",
            ENV_TEMPLATE_POINTS,
            names=ENV_TEMPLATE_NAMES,
            key="env_template",
        ),
        _given(policy) if profile == RepoType.PERSONAL else policy,
    )


def _code_quality(profile: RepoType) -> tuple[GuideCheck, ...]:
    personal = profile == RepoType.PERSONAL
    type_checker = GuideCheck(
        "Type checker config",
        "Configuration for a static type checker.",
        TYPE_CHECKER_POINTS,
        names=TYPE_CHECKER_CONFIG_NAMES,
        key="type_checker",
    )
    pre_commit = GuideCheck(
        "Pre-commit hooks",
        "Checks that run automatically before each commit.",
        PRE_COMMIT_POINTS,
        names=PRE_COMMIT_CONFIG_NAMES,
        key="pre_commit",
    )
    return (
        GuideCheck(
            "Linter or formatter config",
            "Configuration for a linter or formatter.",
            LINTER_CONFIG_POINTS,
            # Names covered by a prefix are shown once, as a pattern
            names=(
                *(
                    name
                    for name in LINTER_CONFIG_NAMES
                    if not name.startswith(LINTER_CONFIG_PREFIXES)
                ),
                *(f"{prefix}*" for prefix in LINTER_CONFIG_PREFIXES),
            ),
            key="linter",
        ),
        _given(type_checker) if personal else type_checker,
        _given(pre_commit) if personal else pre_commit,
    )


# Dimension key -> (the question it answers, function listing its checks)
_DIMENSIONS: dict[str, tuple[str, Callable[[RepoType], tuple[GuideCheck, ...]]]] = {
    "documentation": ("Can a newcomer understand and legally use it?", _documentation),
    "activity": ("Is anyone still working on it?", _activity),
    "organization": ("Is the code laid out the way tools and people expect?", _organization),
    "community": ("Do other people use and contribute to it?", _community),
    "maintainability": ("Is there automation, and is the backlog under control?", _maintainability),
    "security": ("Are the basic safeguards in place?", _security),
    "code_quality": ("Is quality enforced by tools rather than by memory?", _code_quality),
}


def build_scoring_guide(profile: RepoType | str = RepoType.LIBRARY) -> list[GuideDimension]:
    """Returns the seven dimensions with their checks as they apply to `profile`."""
    profile = RepoType(profile)
    return [
        GuideDimension(
            key=key,
            label=DIMENSION_LABELS[key],
            max_points=DIMENSION_MAX_POINTS[key],
            question=question,
            checks=list_checks(profile),
        )
        for key, (question, list_checks) in _DIMENSIONS.items()
    ]


def grade_ranges() -> list[tuple[str, int, int]]:
    """Letter grades as (grade, lowest score, highest score), best first."""
    ranges = []
    upper = 100
    for grade, lowest in GRADE_SCALE:
        ranges.append((grade, lowest, upper))
        upper = lowest - 1
    return ranges


def tier_ranges() -> list[tuple[str, str, int, int]]:
    """Score tiers as (key, label, lowest score, highest score), best first."""
    ranges = []
    upper = 100
    for tier in SCORE_TIERS:
        ranges.append((tier.key, tier.label, tier.min_score, upper))
        upper = tier.min_score - 1
    return ranges


def profile_options() -> list[tuple[str, str, str]]:
    """The scoring profiles as (value, label, description), for the profile switcher."""
    return [
        (profile.value, PROFILE_LABELS[profile], PROFILE_DESCRIPTIONS[profile])
        for profile in RepoType
    ]
