import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("ArchLens.metrics_service")


class RepoType(StrEnum):
    """Repository evaluation profiles supported by the scoring engine."""

    LIBRARY = "library"
    PERSONAL = "personal"
    ENTERPRISE = "enterprise"


# Names shown in forms and reports
PROFILE_LABELS = {
    RepoType.LIBRARY: "Open-source library",
    RepoType.PERSONAL: "Personal project",
    RepoType.ENTERPRISE: "Enterprise app",
}


@dataclass(frozen=True)
class ScoreTier:
    """A named score band; `key` doubles as the CSS modifier (score-high, tier-high...)."""

    key: str
    label: str
    min_score: int


# Single source of truth for score bands, used by the executive summary,
# the web templates and the CLI. Ordered from highest to lowest.
SCORE_TIERS = (
    ScoreTier("high", "Strong Codebase", 70),
    ScoreTier("mid", "Moderate Health", 40),
    ScoreTier("low", "Needs Optimization", 0),
)

# Display names of the seven dimensions, in report order
DIMENSION_LABELS = {
    "documentation": "Documentation",
    "activity": "Activity",
    "organization": "Organization",
    "community": "Community",
    "maintainability": "Maintainability",
    "security": "Security",
    "code_quality": "Code quality",
}

# Maximum points per dimension (they add up to 100)
DIMENSION_MAX_POINTS = {
    "documentation": 15,
    "activity": 15,
    "organization": 15,
    "community": 15,
    "maintainability": 15,
    "security": 12,
    "code_quality": 13,
}

# Letter grades and the lowest score that earns each one, best first
GRADE_SCALE = (
    ("A+", 95),
    ("A", 85),
    ("B+", 75),
    ("B", 65),
    ("C", 50),
    ("D", 35),
    ("F", 0),
)

# GitHub list endpoints are read one page at a time, so counts stop at this value
API_PAGE_CAP = 100


# ---------------------------------------------------------------------------
# Scoring rules
#
# Every point value, threshold and file name the scorer uses is defined here.
# The MetricsService methods below apply them, and the "How scoring works" page
# (app/services/scoring_guide.py) renders the same constants, so the page and
# the scorer cannot disagree. tests/unit/test_scoring_guide.py checks that the
# points in each dimension add up to DIMENSION_MAX_POINTS for every profile.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Band:
    """Partial credit: `points` are awarded when a measured value reaches `limit`."""

    limit: int
    points: int


# Documentation
README_POINTS = 7
LICENSE_POINTS = 4
CONTRIBUTING_OR_DOCS_POINTS = 4
PERSONAL_README_POINTS = 15  # the personal profile only asks for a README
DOCS_DIR_NAMES = ("docs", "doc")

# Activity. Commit bands are minimums; push bands are the most days since the last push.
COMMIT_BANDS = (Band(10, 8), Band(3, 4), Band(1, 2))
PUSH_RECENCY_BANDS = (Band(30, 7), Band(90, 4), Band(180, 2))

# Organization
TESTS_DIR_POINTS = 6
SOURCE_DIR_POINTS = 5
CONFIG_FILES_POINTS = 4
PERSONAL_SOURCE_DIR_POINTS = 8
PERSONAL_CONFIG_FILES_POINTS = 7
TEST_DIR_NAMES = ("tests", "test", "spec", "testing")
SOURCE_DIR_NAMES = ("src", "app", "lib", "sources", "pkg")
CONFIG_FILE_EXTENSIONS = (".toml", ".ini", ".json", ".yaml", ".yml", ".txt", ".lock")
CONFIG_FILE_NAMES = ("setup.py", "makefile", "dockerfile", "gemfile", "go.mod", "cargo.toml")

# Community (minimums). Personal and enterprise projects are not judged on popularity.
STAR_BANDS = (Band(50, 5), Band(10, 3))
FORK_BANDS = (Band(20, 5), Band(5, 3))
CONTRIBUTOR_BANDS = (Band(5, 5), Band(2, 3))
COMMUNITY_WAIVED_PROFILES = (RepoType.PERSONAL, RepoType.ENTERPRISE)

# Maintainability. Issue and size bands are maximums (size in KB, as GitHub reports it).
WORKFLOW_POINTS = 7
OPEN_ISSUE_BANDS = (Band(0, 4), Band(10, 2))
REPO_SIZE_BANDS_KB = (Band(50_000, 4), Band(200_000, 2))

# Security
GITIGNORE_POINTS = 3
LOCKFILE_POINTS = 4
ENV_TEMPLATE_POINTS = 2
SECURITY_POLICY_POINTS = 3
LOCKFILE_NAMES = (
    "requirements.txt",
    "poetry.lock",
    "pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "cargo.lock",
    "go.sum",
    "gemfile.lock",
)
ENV_TEMPLATE_NAMES = (".env.example", ".env.sample", ".env.template")

# Code quality
LINTER_CONFIG_POINTS = 5
TYPE_CHECKER_POINTS = 4
PRE_COMMIT_POINTS = 4
LINTER_CONFIG_NAMES = (
    "pyproject.toml",
    "ruff.toml",
    ".ruff.toml",
    ".flake8",
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.json",
    "biome.json",
    ".prettierrc",
)
LINTER_CONFIG_PREFIXES = (".eslintrc", ".prettierrc")
TYPE_CHECKER_CONFIG_NAMES = ("mypy.ini", ".mypy.ini", "tsconfig.json")
PRE_COMMIT_CONFIG_NAMES = (".pre-commit-config.yaml", ".pre-commit-config.yml")


def score_tier(score: float) -> ScoreTier:
    """Returns the tier for a 0-100 score."""
    for tier in SCORE_TIERS:
        if score >= tier.min_score:
            return tier
    return SCORE_TIERS[-1]


def grade_for_score(score: int) -> str:
    """Maps a 0-100 score to its letter grade: A+, A, B+, B, C, D or F."""
    for grade, min_score in GRADE_SCALE:
        if score >= min_score:
            return grade
    return GRADE_SCALE[-1][0]


def format_capped_count(count: int, cap: int = API_PAGE_CAP) -> str:
    """Formats a count read from a single API page, e.g. 100 -> '100+'."""
    return f"{count:,}+" if count >= cap else f"{count:,}"


def _as_clause(finding: str) -> str:
    """
    Turns a finding sentence into a clause that can be embedded in a summary:
    drops the final period and lowercases the first word unless it is an acronym.
    """
    text = finding.strip().rstrip(".")
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        text = text[0].lower() + text[1:]
    return text


class MetricsService:
    """
    Calculates engineering quality scores and compiles recommendations for a repository.
    The overall health score (0-100) is aggregated across 7 dimensions:
      - Documentation (Max: 15)
      - Activity & Velocity (Max: 15)
      - Code Organization (Max: 15)
      - Community Engagement (Max: 15)
      - Maintainability & CI/CD (Max: 15)
      - Security Standards (Max: 12)
      - Code Quality & Tooling (Max: 13)

    Adjusts scoring curves dynamically based on repo_type ('personal', 'library', 'enterprise').
    Point values and thresholds come from the scoring rule constants above.
    """

    def calculate_documentation_score(
        self, root_contents: list[dict[str, Any]], repo_type: str
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates repository documentation level (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_readme = False
        has_license = False
        has_contributing = False
        has_docs_dir = False

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "file" and name.startswith("readme"):
                has_readme = True
            elif item_type == "file" and (name.startswith("license") or name == "copying"):
                has_license = True
            elif item_type == "file" and name.startswith("contributing"):
                has_contributing = True
            elif item_type == "dir" and name in DOCS_DIR_NAMES:
                has_docs_dir = True

        if has_readme:
            strengths.append("Found repository README.")
        else:
            weaknesses.append("Missing README file in root directory.")
            suggestions.append("Add a README.md file in the root.")

        if repo_type == RepoType.PERSONAL:
            if has_readme:
                score += PERSONAL_README_POINTS
        else:
            if has_readme:
                score += README_POINTS
            if has_license:
                score += LICENSE_POINTS
                strengths.append("Found LICENSE permissions file.")
            else:
                weaknesses.append("Missing LICENSE file.")
                suggestions.append("Add a LICENSE file.")

            if has_contributing or has_docs_dir:
                score += CONTRIBUTING_OR_DOCS_POINTS
                strengths.append("Found documentation/contributing guidelines.")
            else:
                weaknesses.append("Missing CONTRIBUTING guide or docs folder.")
                suggestions.append("Create a CONTRIBUTING.md file or docs/ folder.")

        return score, strengths, weaknesses, suggestions

    def calculate_activity_score(
        self,
        metadata: dict[str, Any],
        recent_commits: list[dict[str, Any]],
        repo_type: str,
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates repository release frequency and developer activity (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        busy, steady, occasional = COMMIT_BANDS
        commit_count = len(recent_commits)
        if commit_count >= busy.limit:
            score += busy.points
            strengths.append(
                f"High commit activity: {format_capped_count(commit_count)} commits in the last 30 days."
            )
        elif commit_count >= steady.limit:
            score += steady.points
            strengths.append(
                f"Moderate commit activity: {commit_count} commits in the last 30 days."
            )
        elif commit_count >= occasional.limit:
            score += occasional.points
            strengths.append(f"Low commit activity: {commit_count} commit(s) in the last 30 days.")
        else:
            weaknesses.append("Zero commit activity recorded in the last 30 days.")
            suggestions.append("Commit updates periodically to keep the repository active.")

        pushed_at_str = metadata.get("pushed_at")
        days_since_push = 999
        if pushed_at_str:
            try:
                pushed_dt = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
                days_since_push = (datetime.now(UTC).replace(tzinfo=None) - pushed_dt).days
            except Exception as e:
                logger.error(f"Error parsing pushed_at timestamp '{pushed_at_str}': {e}")

        recent, quarter, half_year = PUSH_RECENCY_BANDS
        if days_since_push <= recent.limit:
            score += recent.points
            strengths.append("Repository updated recently (within the last 30 days).")
        elif days_since_push <= quarter.limit:
            score += quarter.points
            strengths.append(
                f"Repository updated recently (last pushed {days_since_push} days ago)."
            )
        elif days_since_push <= half_year.limit:
            score += half_year.points
            weaknesses.append(
                f"Repository is becoming inactive (last pushed {days_since_push} days ago)."
            )
            suggestions.append("Resume updates to prevent the repository from becoming stale.")
        else:
            weaknesses.append(f"Repository is stale (last pushed {days_since_push} days ago).")
            suggestions.append("Resume repository updates.")

        return score, strengths, weaknesses, suggestions

    def calculate_organization_score(
        self, root_contents: list[dict[str, Any]], repo_type: str
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates directory layouts and configuration file standards (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_tests = False
        has_src = False
        has_configs = False

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "dir" and name in TEST_DIR_NAMES:
                has_tests = True
            elif item_type == "dir" and name in SOURCE_DIR_NAMES:
                has_src = True
            elif item_type == "file" and (
                name.startswith(".")
                or name in CONFIG_FILE_NAMES
                or name.endswith(CONFIG_FILE_EXTENSIONS)
            ):
                has_configs = True

        if repo_type == RepoType.PERSONAL:
            if has_src:
                score += PERSONAL_SOURCE_DIR_POINTS
            if has_configs:
                score += PERSONAL_CONFIG_FILES_POINTS
        else:
            if has_tests:
                score += TESTS_DIR_POINTS
                strengths.append("Found dedicated test suite directory.")
            else:
                weaknesses.append("Missing test suite folder.")
                suggestions.append("Create a tests/ directory.")

            if has_src:
                score += SOURCE_DIR_POINTS
                strengths.append("Source code organized into a dedicated subdirectory.")
            else:
                weaknesses.append("Missing standard source code folder.")

            if has_configs:
                score += CONFIG_FILES_POINTS
                strengths.append("Found workspace configuration files.")
            else:
                weaknesses.append("Missing standard environment configuration files.")

        return score, strengths, weaknesses, suggestions

    def calculate_community_score(
        self, metadata: dict[str, Any], contributor_count: int, repo_type: str
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates repository community engagement based on stars, forks, and contributors (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        if repo_type in COMMUNITY_WAIVED_PROFILES:
            score = DIMENSION_MAX_POINTS["community"]
            strengths.append("Community metrics bypassed for Personal/Enterprise profile.")
            return score, strengths, weaknesses, suggestions

        stars = metadata.get("stargazers_count", 0) or 0
        forks = metadata.get("forks_count", 0) or 0

        many_stars, some_stars = STAR_BANDS
        if stars >= many_stars.limit:
            score += many_stars.points
            strengths.append(f"Strong community interest with {stars:,} stars.")
        elif stars >= some_stars.limit:
            score += some_stars.points
            strengths.append(f"Growing community interest with {stars} stars.")
        else:
            weaknesses.append(f"Low community visibility with {stars} star(s).")
            suggestions.append("Promote your repository on developer communities.")

        many_forks, some_forks = FORK_BANDS
        if forks >= many_forks.limit:
            score += many_forks.points
            strengths.append(f"High fork count ({forks:,}).")
        elif forks >= some_forks.limit:
            score += some_forks.points
            strengths.append(f"Moderate fork activity ({forks} forks).")
        else:
            weaknesses.append(f"Low fork count ({forks}).")

        many_contributors, some_contributors = CONTRIBUTOR_BANDS
        if contributor_count >= many_contributors.limit:
            score += many_contributors.points
            strengths.append(
                f"Active contributor base with {format_capped_count(contributor_count)} contributors."
            )
        elif contributor_count >= some_contributors.limit:
            score += some_contributors.points
            strengths.append(f"Small active contributor group ({contributor_count} contributors).")
        else:
            weaknesses.append("Only a single contributor.")
            suggestions.append("Open issues for good first contributions.")

        return score, strengths, weaknesses, suggestions

    def calculate_maintainability_score(
        self,
        metadata: dict[str, Any],
        workflow_contents: list[dict[str, Any]],
        repo_type: str,
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates CI/CD setup, open issue management, and repository size health (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_workflows = len(workflow_contents) > 0
        if has_workflows:
            score += WORKFLOW_POINTS
            strengths.append(f"Found {len(workflow_contents)} GitHub Actions workflow(s).")
        else:
            if repo_type == RepoType.PERSONAL:
                score += WORKFLOW_POINTS
            else:
                weaknesses.append("No GitHub Actions workflows detected.")
                suggestions.append("Add a GitHub Actions workflow.")

        no_issues, few_issues = OPEN_ISSUE_BANDS
        open_issues = metadata.get("open_issues_count", 0) or 0
        if open_issues <= no_issues.limit:
            score += no_issues.points
            strengths.append("Zero open issues.")
        elif open_issues <= few_issues.limit:
            score += few_issues.points
            strengths.append(f"Manageable open issue count ({open_issues} issues).")
        else:
            weaknesses.append(f"High open issue count ({open_issues:,}).")

        lean, moderate = REPO_SIZE_BANDS_KB
        repo_size_kb = metadata.get("size", 0) or 0
        if repo_size_kb <= lean.limit:
            score += lean.points
            strengths.append("Repository size is lean and well-managed.")
        elif repo_size_kb <= moderate.limit:
            score += moderate.points
            strengths.append("Repository size is moderate.")
        else:
            weaknesses.append(f"Repository is large ({repo_size_kb // 1024}MB).")
            suggestions.append("Clean up large artifacts.")

        return score, strengths, weaknesses, suggestions

    def calculate_security_score(
        self, root_contents: list[dict[str, Any]], repo_type: str
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates security policies, environment secrets protection, and dependency lockfiles (Max: 12 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_security_md = False
        has_env_example = False
        has_gitignore = False
        has_lockfile = False

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "file":
                if name.startswith("security"):
                    has_security_md = True
                elif name in ENV_TEMPLATE_NAMES:
                    has_env_example = True
                elif name == ".gitignore":
                    has_gitignore = True
                elif name in LOCKFILE_NAMES:
                    has_lockfile = True

        if has_gitignore:
            score += GITIGNORE_POINTS
            strengths.append("Found .gitignore secret protection file.")
        else:
            weaknesses.append("Missing .gitignore file (risk of committing secrets).")
            suggestions.append("Add a .gitignore file to prevent checking in credentials.")

        if has_lockfile:
            score += LOCKFILE_POINTS
            strengths.append("Found dependency lockfile for deterministic builds.")
        else:
            weaknesses.append(
                "Missing dependency lockfile (e.g. requirements.txt, package-lock.json)."
            )
            suggestions.append("Commit a dependency lockfile for reproducible deployments.")

        if has_env_example:
            score += ENV_TEMPLATE_POINTS
            strengths.append("Found environment variable template (.env.example).")

        if has_security_md:
            score += SECURITY_POLICY_POINTS
            strengths.append("Found explicit SECURITY.md policy.")
        else:
            if repo_type == RepoType.PERSONAL:
                score += SECURITY_POLICY_POINTS
            else:
                weaknesses.append("Missing SECURITY.md vulnerability reporting policy.")
                suggestions.append("Add a SECURITY.md file detailing security issue reporting.")

        return score, strengths, weaknesses, suggestions

    def calculate_code_quality_score(
        self, root_contents: list[dict[str, Any]], repo_type: str
    ) -> tuple[int, list[str], list[str], list[str]]:
        """
        Evaluates static analysis tools, linters, formatters, and type checkers (Max: 13 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_linter_config = False
        has_type_config = False
        has_pre_commit = False

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "file":
                if name in LINTER_CONFIG_NAMES or name.startswith(LINTER_CONFIG_PREFIXES):
                    has_linter_config = True
                elif name in TYPE_CHECKER_CONFIG_NAMES:
                    has_type_config = True
                elif name in PRE_COMMIT_CONFIG_NAMES:
                    has_pre_commit = True

        if has_linter_config:
            score += LINTER_CONFIG_POINTS
            strengths.append(
                "Found linter/formatter configuration (Ruff/ESLint/Prettier/pyproject.toml)."
            )
        else:
            weaknesses.append("Missing explicit linter or formatter configuration.")
            suggestions.append(
                "Configure a linter (e.g. Ruff, ESLint, or Black) in pyproject.toml."
            )

        if has_type_config:
            score += TYPE_CHECKER_POINTS
            strengths.append("Found static type checking configuration (mypy / tsconfig).")
        else:
            if repo_type == RepoType.PERSONAL:
                score += TYPE_CHECKER_POINTS
            else:
                weaknesses.append("Missing explicit static type checker configuration.")
                suggestions.append(
                    "Add static type checking configuration (e.g. mypy.ini or tsconfig.json)."
                )

        if has_pre_commit:
            score += PRE_COMMIT_POINTS
            strengths.append("Found .pre-commit-config.yaml git hooks automation.")
        else:
            if repo_type == RepoType.PERSONAL:
                score += PRE_COMMIT_POINTS
            else:
                weaknesses.append("No pre-commit git hooks detected.")
                suggestions.append(
                    "Add a .pre-commit-config.yaml file to enforce quality on git commit."
                )

        return score, strengths, weaknesses, suggestions

    def compute_health_grade(self, overall_score: int) -> str:
        """
        Maps numeric score (0-100) to a letter grade: A+, A, B+, B, C, D, or F.
        """
        return grade_for_score(overall_score)

    def generate_executive_summary(
        self,
        score: int,
        grade: str,
        repo_type: str,
        strengths: list[str],
        weaknesses: list[str],
    ) -> str:
        """
        Generates a concise 2-3 sentence natural language executive summary.
        """
        tier = score_tier(score)
        profile_label = "open-source library" if repo_type == "library" else f"{repo_type} project"

        summary = (
            f"This {profile_label} scored {score}/100 (Grade: {grade}), "
            f"placing it in the {tier.label} tier."
        )

        top_strengths = [_as_clause(s) for s in strengths[:2]]
        if len(top_strengths) == 2:
            summary += f" Key strengths: {top_strengths[0]}; {top_strengths[1]}."
        elif top_strengths:
            summary += f" Key strength: {top_strengths[0]}."

        if weaknesses:
            summary += f" Primary area for improvement: {_as_clause(weaknesses[0])}."
        else:
            summary += " No critical weaknesses were identified across analyzed dimensions."

        return summary

    def calculate_overall_report(
        self,
        metadata: dict[str, Any],
        languages: dict[str, int],
        root_contents: list[dict[str, Any]],
        contributor_count: int,
        recent_commits: list[dict[str, Any]],
        workflow_contents: list[dict[str, Any]],
        repo_type: str = "library",
    ) -> dict[str, Any]:
        """
        Orchestrates the full 7-dimension scoring report.
        """
        doc_score, doc_str, doc_weak, doc_sug = self.calculate_documentation_score(
            root_contents, repo_type
        )
        act_score, act_str, act_weak, act_sug = self.calculate_activity_score(
            metadata, recent_commits, repo_type
        )
        org_score, org_str, org_weak, org_sug = self.calculate_organization_score(
            root_contents, repo_type
        )
        com_score, com_str, com_weak, com_sug = self.calculate_community_score(
            metadata, contributor_count, repo_type
        )
        mnt_score, mnt_str, mnt_weak, mnt_sug = self.calculate_maintainability_score(
            metadata, workflow_contents, repo_type
        )
        sec_score, sec_str, sec_weak, sec_sug = self.calculate_security_score(
            root_contents, repo_type
        )
        qlty_score, qlty_str, qlty_weak, qlty_sug = self.calculate_code_quality_score(
            root_contents, repo_type
        )

        breakdown = {
            "documentation": doc_score,
            "activity": act_score,
            "organization": org_score,
            "community": com_score,
            "maintainability": mnt_score,
            "security": sec_score,
            "code_quality": qlty_score,
        }

        overall_score = min(
            100,
            doc_score + act_score + org_score + com_score + mnt_score + sec_score + qlty_score,
        )

        all_strengths = doc_str + act_str + org_str + com_str + mnt_str + sec_str + qlty_str
        all_weaknesses = doc_weak + act_weak + org_weak + com_weak + mnt_weak + sec_weak + qlty_weak
        all_suggestions = doc_sug + act_sug + org_sug + com_sug + mnt_sug + sec_sug + qlty_sug

        health_grade = self.compute_health_grade(overall_score)
        executive_summary = self.generate_executive_summary(
            score=overall_score,
            grade=health_grade,
            repo_type=repo_type,
            strengths=all_strengths,
            weaknesses=all_weaknesses,
        )

        return {
            "overall_score": overall_score,
            "health_grade": health_grade,
            "executive_summary": executive_summary,
            "security_score": sec_score,
            "code_quality_score": qlty_score,
            "breakdown": breakdown,
            "strengths": all_strengths,
            "weaknesses": all_weaknesses,
            "suggestions": all_suggestions,
        }
