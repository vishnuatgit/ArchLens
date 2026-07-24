import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("ArchLens.metrics_service")


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
    """

    def calculate_documentation_score(
        self, root_contents: List[Dict[str, Any]], repo_type: str
    ) -> Tuple[int, List[str], List[str], List[str]]:
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

            if item_type == "file":
                if name.startswith("readme"):
                    has_readme = True
                elif name.startswith("license") or name == "copying":
                    has_license = True
                elif name.startswith("contributing"):
                    has_contributing = True
            elif item_type == "dir":
                if name in ["docs", "doc"]:
                    has_docs_dir = True

        if has_readme:
            strengths.append("Found repository README.")
        else:
            weaknesses.append("Missing README file in root directory.")
            suggestions.append("Add a README.md file in the root.")

        if repo_type == "personal":
            if has_readme:
                score += 15
        else:
            if has_readme:
                score += 7
            if has_license:
                score += 4
                strengths.append("Found LICENSE permissions file.")
            else:
                weaknesses.append("Missing LICENSE file.")
                suggestions.append("Add a LICENSE file.")

            if has_contributing or has_docs_dir:
                score += 4
                strengths.append("Found documentation/contributing guidelines.")
            else:
                weaknesses.append("Missing CONTRIBUTING guide or docs folder.")
                suggestions.append("Create a CONTRIBUTING.md file or docs/ folder.")

        return score, strengths, weaknesses, suggestions

    def calculate_activity_score(
        self,
        metadata: Dict[str, Any],
        recent_commits: List[Dict[str, Any]],
        repo_type: str,
    ) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository release frequency and developer activity (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        commit_count = len(recent_commits)
        if commit_count >= 10:
            score += 8
            strengths.append(
                f"High commit activity: {commit_count} commits in the last 30 days."
            )
        elif commit_count >= 3:
            score += 4
            strengths.append(
                f"Moderate commit activity: {commit_count} commits in the last 30 days."
            )
        elif commit_count >= 1:
            score += 2
            strengths.append(
                f"Low commit activity: {commit_count} commit(s) in the last 30 days."
            )
        else:
            weaknesses.append("Zero commit activity recorded in the last 30 days.")
            suggestions.append(
                "Commit updates periodically to keep the repository active."
            )

        pushed_at_str = metadata.get("pushed_at")
        days_since_push = 999
        if pushed_at_str:
            try:
                pushed_dt = datetime.fromisoformat(
                    pushed_at_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                days_since_push = (
                    datetime.now(timezone.utc).replace(tzinfo=None) - pushed_dt
                ).days
            except Exception as e:
                logger.error(
                    f"Error parsing pushed_at timestamp '{pushed_at_str}': {e}"
                )

        if days_since_push <= 30:
            score += 7
            strengths.append("Repository updated recently (within the last 30 days).")
        elif days_since_push <= 90:
            score += 4
            strengths.append(
                f"Repository updated recently (last pushed {days_since_push} days ago)."
            )
        elif days_since_push <= 180:
            score += 2
            weaknesses.append(
                f"Repository is becoming inactive (last pushed {days_since_push} days ago)."
            )
            suggestions.append(
                "Resume updates to prevent the repository from becoming stale."
            )
        else:
            weaknesses.append(
                f"Repository is stale (last pushed {days_since_push} days ago)."
            )
            suggestions.append("Resume repository updates.")

        return score, strengths, weaknesses, suggestions

    def calculate_organization_score(
        self, root_contents: List[Dict[str, Any]], repo_type: str
    ) -> Tuple[int, List[str], List[str], List[str]]:
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

        config_extensions = [".toml", ".ini", ".json", ".yaml", ".yml", ".txt", ".lock"]
        config_basenames = [
            "setup.py",
            "makefile",
            "dockerfile",
            "gemfile",
            "go.mod",
            "cargo.toml",
        ]

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "dir":
                if name in ["tests", "test", "spec", "testing"]:
                    has_tests = True
                elif name in ["src", "app", "lib", "sources", "pkg"]:
                    has_src = True
            elif item_type == "file":
                if (
                    name.startswith(".")
                    or name in config_basenames
                    or any(name.endswith(ext) for ext in config_extensions)
                ):
                    has_configs = True

        if repo_type == "personal":
            if has_src:
                score += 8
            if has_configs:
                score += 7
        else:
            if has_tests:
                score += 6
                strengths.append("Found dedicated test suite directory.")
            else:
                weaknesses.append("Missing test suite folder.")
                suggestions.append("Create a tests/ directory.")

            if has_src:
                score += 5
                strengths.append("Source code organized into a dedicated subdirectory.")
            else:
                weaknesses.append("Missing standard source code folder.")

            if has_configs:
                score += 4
                strengths.append("Found workspace configuration files.")
            else:
                weaknesses.append("Missing standard environment configuration files.")

        return score, strengths, weaknesses, suggestions

    def calculate_community_score(
        self, metadata: Dict[str, Any], contributor_count: int, repo_type: str
    ) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository community engagement based on stars, forks, and contributors (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        if repo_type in ["personal", "enterprise"]:
            score = 15
            strengths.append(
                "Community metrics bypassed for Personal/Enterprise profile."
            )
            return score, strengths, weaknesses, suggestions

        stars = metadata.get("stargazers_count", 0) or 0
        forks = metadata.get("forks_count", 0) or 0

        if stars >= 50:
            score += 5
            strengths.append(f"Strong community interest with {stars} stars.")
        elif stars >= 10:
            score += 3
            strengths.append(f"Growing community interest with {stars} stars.")
        else:
            weaknesses.append(f"Low community visibility with {stars} star(s).")
            suggestions.append("Promote your repository on developer communities.")

        if forks >= 20:
            score += 5
            strengths.append(f"High fork count ({forks}).")
        elif forks >= 5:
            score += 3
            strengths.append(f"Moderate fork activity ({forks} forks).")
        else:
            weaknesses.append(f"Low fork count ({forks}).")

        if contributor_count >= 5:
            score += 5
            strengths.append(
                f"Active contributor base with {contributor_count} contributors."
            )
        elif contributor_count >= 2:
            score += 3
            strengths.append(
                f"Small active contributor group ({contributor_count} contributors)."
            )
        else:
            weaknesses.append("Only a single contributor.")
            suggestions.append("Open issues for good first contributions.")

        return score, strengths, weaknesses, suggestions

    def calculate_maintainability_score(
        self,
        metadata: Dict[str, Any],
        workflow_contents: List[Dict[str, Any]],
        repo_type: str,
    ) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates CI/CD setup, open issue management, and repository size health (Max: 15 points).
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_workflows = len(workflow_contents) > 0
        if has_workflows:
            score += 7
            strengths.append(
                f"Found {len(workflow_contents)} GitHub Actions workflow(s)."
            )
        else:
            if repo_type == "personal":
                score += 7
            else:
                weaknesses.append("No GitHub Actions workflows detected.")
                suggestions.append("Add a GitHub Actions workflow.")

        open_issues = metadata.get("open_issues_count", 0) or 0
        if open_issues == 0:
            score += 4
            strengths.append("Zero open issues.")
        elif open_issues <= 10:
            score += 2
            strengths.append(f"Manageable open issue count ({open_issues} issues).")
        else:
            weaknesses.append(f"High open issue count ({open_issues}).")

        repo_size_kb = metadata.get("size", 0) or 0
        if repo_size_kb <= 50000:
            score += 4
            strengths.append("Repository size is lean and well-managed.")
        elif repo_size_kb <= 200000:
            score += 2
            strengths.append("Repository size is moderate.")
        else:
            weaknesses.append(f"Repository is large ({repo_size_kb // 1024}MB).")
            suggestions.append("Clean up large artifacts.")

        return score, strengths, weaknesses, suggestions

    def calculate_security_score(
        self, root_contents: List[Dict[str, Any]], repo_type: str
    ) -> Tuple[int, List[str], List[str], List[str]]:
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

        lockfile_names = [
            "requirements.txt",
            "poetry.lock",
            "pipfile.lock",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "cargo.lock",
            "go.sum",
            "gemfile.lock",
        ]

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "file":
                if name.startswith("security"):
                    has_security_md = True
                elif name in [".env.example", ".env.sample", ".env.template"]:
                    has_env_example = True
                elif name == ".gitignore":
                    has_gitignore = True
                elif name in lockfile_names:
                    has_lockfile = True

        if has_gitignore:
            score += 3
            strengths.append("Found .gitignore secret protection file.")
        else:
            weaknesses.append("Missing .gitignore file (risk of committing secrets).")
            suggestions.append("Add a .gitignore file to prevent checking in credentials.")

        if has_lockfile:
            score += 4
            strengths.append("Found dependency lockfile for deterministic builds.")
        else:
            weaknesses.append("Missing dependency lockfile (e.g. requirements.txt, package-lock.json).")
            suggestions.append("Commit a dependency lockfile for reproducible deployments.")

        if has_env_example:
            score += 2
            strengths.append("Found environment variable template (.env.example).")

        if has_security_md:
            score += 3
            strengths.append("Found explicit SECURITY.md policy.")
        else:
            if repo_type == "personal":
                score += 3
            else:
                weaknesses.append("Missing SECURITY.md vulnerability reporting policy.")
                suggestions.append("Add a SECURITY.md file detailing security issue reporting.")

        return score, strengths, weaknesses, suggestions

    def calculate_code_quality_score(
        self, root_contents: List[Dict[str, Any]], repo_type: str
    ) -> Tuple[int, List[str], List[str], List[str]]:
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

        linter_names = [
            "pyproject.toml",
            "ruff.toml",
            ".ruff.toml",
            ".flake8",
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.json",
            "biome.json",
            ".prettierrc",
        ]
        type_names = ["mypy.ini", ".mypy.ini", "tsconfig.json"]

        for item in root_contents:
            name = item.get("name", "").lower()
            item_type = item.get("type", "")

            if item_type == "file":
                if name in linter_names or any(name.startswith(l) for l in [".eslintrc", ".prettierrc"]):
                    has_linter_config = True
                elif name in type_names:
                    has_type_config = True
                elif name in [".pre-commit-config.yaml", ".pre-commit-config.yml"]:
                    has_pre_commit = True

        if has_linter_config:
            score += 5
            strengths.append("Found linter/formatter configuration (Ruff/ESLint/Prettier/pyproject.toml).")
        else:
            weaknesses.append("Missing explicit linter or formatter configuration.")
            suggestions.append("Configure a linter (e.g. Ruff, ESLint, or Black) in pyproject.toml.")

        if has_type_config:
            score += 4
            strengths.append("Found static type checking configuration (mypy / tsconfig).")
        else:
            if repo_type == "personal":
                score += 4
            else:
                weaknesses.append("Missing explicit static type checker configuration.")
                suggestions.append("Add static type checking configuration (e.g. mypy.ini or tsconfig.json).")

        if has_pre_commit:
            score += 4
            strengths.append("Found .pre-commit-config.yaml git hooks automation.")
        else:
            if repo_type == "personal":
                score += 4
            else:
                weaknesses.append("No pre-commit git hooks detected.")
                suggestions.append("Add a .pre-commit-config.yaml file to enforce quality on git commit.")

        return score, strengths, weaknesses, suggestions

    def compute_health_grade(self, overall_score: int) -> str:
        """
        Maps numeric score (0-100) to a letter grade: A+, A, B+, B, C, D, or F.
        """
        if overall_score >= 95:
            return "A+"
        elif overall_score >= 85:
            return "A"
        elif overall_score >= 75:
            return "B+"
        elif overall_score >= 65:
            return "B"
        elif overall_score >= 50:
            return "C"
        elif overall_score >= 35:
            return "D"
        else:
            return "F"

    def generate_executive_summary(
        self,
        score: int,
        grade: str,
        repo_type: str,
        strengths: List[str],
        weaknesses: List[str],
    ) -> str:
        """
        Generates a concise 2-3 sentence natural language executive summary.
        """
        tier = "production-grade" if score >= 80 else "moderate-health" if score >= 60 else "needs optimization"
        profile_label = "open-source library" if repo_type == "library" else f"{repo_type} project"

        summary = (
            f"This repository scored {score}/100 (Grade: {grade}) evaluated as a {profile_label}. "
            f"Key strengths include {strengths[0].lower() if strengths else 'a clean structure'} "
            f"and {strengths[1].lower() if len(strengths) > 1 else 'active maintenance'}. "
        )

        if weaknesses:
            summary += f"Primary area for improvement: {weaknesses[0].lower()}."
        else:
            summary += "No critical weaknesses were identified across analyzed dimensions."

        return summary

    def calculate_overall_report(
        self,
        metadata: Dict[str, Any],
        languages: Dict[str, int],
        root_contents: List[Dict[str, Any]],
        contributor_count: int,
        recent_commits: List[Dict[str, Any]],
        workflow_contents: List[Dict[str, Any]],
        repo_type: str = "library",
    ) -> Dict[str, Any]:
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
            doc_score
            + act_score
            + org_score
            + com_score
            + mnt_score
            + sec_score
            + qlty_score,
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

