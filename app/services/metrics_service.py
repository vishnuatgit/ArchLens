import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("ArchLens.metrics_service")

class MetricsService:
    """
    Calculates engineering quality scores and compiles recommendations for a repository.
    The overall health score (0-100) is aggregated across five dimensions (20 points each).
    """

    def calculate_documentation_score(self, root_contents: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository documentation level (Max: 20 points).
        Checks for:
          - README file (10 pts)
          - LICENSE file (5 pts)
          - CONTRIBUTING instructions or docs directory (5 pts)
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

        # README scoring (10 points)
        if has_readme:
            score += 10
            strengths.append("Found repository README detailing project architecture and setup.")
        else:
            weaknesses.append("Missing README file in root directory.")
            suggestions.append("Add a README.md file in the root to introduce your project to developers and SREs.")

        # LICENSE scoring (5 points)
        if has_license:
            score += 5
            strengths.append("Found LICENSE file defining software distribution rules.")
        else:
            weaknesses.append("Missing LICENSE file in repository.")
            suggestions.append("Add a LICENSE file (e.g. MIT, Apache 2.0) to clarify code usage permissions.")

        # CONTRIBUTING & Docs folder scoring (5 points)
        if has_contributing or has_docs_dir:
            score += 5
            resources = []
            if has_contributing:
                resources.append("CONTRIBUTING guidelines")
            if has_docs_dir:
                resources.append("docs directory")
            strengths.append(f"Found repository docs resource: {' and '.join(resources)}.")
        else:
            weaknesses.append("Missing CONTRIBUTING guide and dedicated docs directory.")
            suggestions.append("Create a CONTRIBUTING.md file or a docs/ folder to guide engineers on contribution workflows.")

        return score, strengths, weaknesses, suggestions

    def calculate_activity_score(self, metadata: Dict[str, Any], recent_commits: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository release frequency and developer activity (Max: 20 points).
        Checks for:
          - Recent commits volume (Max 10 pts)
          - Days since last pushed date (Max 10 pts)
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        # 1. Commit volume check (10 points)
        commit_count = len(recent_commits)
        if commit_count >= 10:
            score += 10
            strengths.append(f"High commit activity: {commit_count} commits in the last 30 days.")
        elif commit_count >= 3:
            score += 5
            strengths.append(f"Moderate commit activity: {commit_count} commits in the last 30 days.")
        elif commit_count >= 1:
            score += 2
            strengths.append(f"Low commit activity: Only {commit_count} commit(s) in the last 30 days.")
        else:
            weaknesses.append("Zero commit activity recorded in the last 30 days.")
            suggestions.append("Establish a consistent release cycle and commit updates periodically to keep the repository active.")

        # 2. Last pushed age check (10 points)
        pushed_at_str = metadata.get("pushed_at")
        days_since_push = 999
        if pushed_at_str:
            try:
                # GitHub returns ISO 8601: "YYYY-MM-DDTHH:MM:SSZ"
                pushed_dt = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00")).replace(tzinfo=None)
                days_since_push = (datetime.utcnow() - pushed_dt).days
            except Exception as e:
                logger.error(f"Error parsing pushed_at timestamp '{pushed_at_str}': {str(e)}")

        if days_since_push <= 30:
            score += 10
            strengths.append("Repository updated recently (within the last 30 days).")
        elif days_since_push <= 90:
            score += 5
            strengths.append(f"Repository updated recently (last pushed {days_since_push} days ago).")
        elif days_since_push <= 180:
            score += 2
            weaknesses.append(f"Repository is becoming inactive (last pushed {days_since_push} days ago).")
            suggestions.append("Resume updates to prevent the repository from becoming stale.")
        else:
            weaknesses.append(f"Repository is stale (last pushed {days_since_push} days ago).")
            suggestions.append("Resume repository updates or push commits to demonstrate project lifecycle maintenance.")

        return score, strengths, weaknesses, suggestions

    def calculate_organization_score(self, root_contents: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates directory layouts and configuration file standards (Max: 20 points).
        Checks for:
          - Testing directories (8 pts)
          - Standard source folders (6 pts)
          - Tooling configuration/lock files (6 pts)
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        has_tests = False
        has_src = False
        has_configs = False

        config_extensions = [
            ".toml", ".ini", ".json", ".yaml", ".yml", ".txt", ".lock"
        ]
        config_basenames = [
            "setup.py", "makefile", "dockerfile", "gemfile", "go.mod", "cargo.toml"
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
                # Check for standard tooling configuration files
                if name.startswith(".") or name in config_basenames or any(name.endswith(ext) for ext in config_extensions):
                    has_configs = True

        # Tests folder check (8 points)
        if has_tests:
            score += 8
            strengths.append("Found dedicated test suite directory for verifying software stability.")
        else:
            weaknesses.append("Missing test suite folder (e.g. tests/, test/) in the root directory.")
            suggestions.append("Create a tests/ directory in your root and write automated unit tests for key logic.")

        # Source folder check (6 points)
        if has_src:
            score += 6
            strengths.append("Source code organized into a dedicated subdirectory.")
        else:
            weaknesses.append("Missing standard source code folder (e.g. src/ or app/) in root.")
            suggestions.append("Structure your project by moving code files into an app/ or src/ directory instead of leaving them flat in the root.")

        # Configuration files check (6 points)
        if has_configs:
            score += 6
            strengths.append("Found workspace configuration files (e.g. settings, packages, dependency lock files).")
        else:
            weaknesses.append("Missing standard environment configuration or dependency management files.")
            suggestions.append("Add dependency manifest files (e.g., requirements.txt, pyproject.toml) to standardize workspace configurations.")

        return score, strengths, weaknesses, suggestions

    def calculate_community_score(self, metadata: Dict[str, Any], contributor_count: int) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository community engagement based on stars, forks, and contributors (Max: 20 points).
        Checks for:
          - Stars count (6 pts)
          - Forks count (6 pts)
          - Unique contributor count (8 pts)
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        stars = metadata.get("stargazers_count", 0) or 0
        forks = metadata.get("forks_count", 0) or 0

        # Stars scoring (6 points)
        if stars >= 50:
            score += 6
            strengths.append(f"Strong community interest with {stars} stars.")
        elif stars >= 10:
            score += 3
            strengths.append(f"Growing community interest with {stars} stars.")
        else:
            weaknesses.append(f"Low community visibility with only {stars} star(s).")
            suggestions.append("Promote your repository on developer communities to attract more visibility.")

        # Forks scoring (6 points)
        if forks >= 20:
            score += 6
            strengths.append(f"High fork count ({forks}) indicates active reuse and collaboration.")
        elif forks >= 5:
            score += 3
            strengths.append(f"Moderate fork activity ({forks} forks).")
        else:
            weaknesses.append(f"Low fork count ({forks}) suggests limited external collaboration.")
            suggestions.append("Make the project easier to fork and contribute to by improving documentation.")

        # Contributors scoring (8 points)
        if contributor_count >= 5:
            score += 8
            strengths.append(f"Active contributor base with {contributor_count} contributors.")
        elif contributor_count >= 2:
            score += 4
            strengths.append(f"Small but active contributor group ({contributor_count} contributors).")
        else:
            weaknesses.append("Only a single contributor — repository lacks collaboration.")
            suggestions.append("Open issues for good first contributions and invite collaborators.")

        return score, strengths, weaknesses, suggestions

    def calculate_maintainability_score(self, metadata: Dict[str, Any], workflow_contents: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates CI/CD setup, open issue management, and repository size health (Max: 20 points).
        Checks for:
          - GitHub Actions workflows present (8 pts)
          - Open issues ratio (6 pts)
          - Repository size health (6 pts)
        """
        score = 0
        strengths = []
        weaknesses = []
        suggestions = []

        # CI/CD workflows scoring (8 points)
        has_workflows = len(workflow_contents) > 0
        if has_workflows:
            score += 8
            strengths.append(f"Found {len(workflow_contents)} GitHub Actions workflow(s) for automated CI/CD.")
        else:
            weaknesses.append("No GitHub Actions workflows detected in .github/workflows/.")
            suggestions.append("Add a GitHub Actions workflow to automate testing and linting on every push.")

        # Open issues scoring (6 points)
        open_issues = metadata.get("open_issues_count", 0) or 0
        if open_issues == 0:
            score += 6
            strengths.append("Zero open issues — repository is well-maintained.")
        elif open_issues <= 10:
            score += 3
            strengths.append(f"Manageable open issue count ({open_issues} issues).")
        else:
            weaknesses.append(f"High open issue count ({open_issues}) may indicate maintenance debt.")
            suggestions.append("Triage and close stale open issues to demonstrate active maintenance.")

        # Repository size scoring (6 points)
        repo_size_kb = metadata.get("size", 0) or 0
        if repo_size_kb <= 50000:  # up to ~50MB
            score += 6
            strengths.append("Repository size is lean and well-managed.")
        elif repo_size_kb <= 200000:  # up to ~200MB
            score += 3
            strengths.append("Repository size is moderate.")
        else:
            weaknesses.append(f"Repository is large ({repo_size_kb // 1024}MB) — consider cleaning up binaries or large assets.")
            suggestions.append("Use .gitignore to exclude build artifacts, binaries, and large generated files.")

        return score, strengths, weaknesses, suggestions

    def calculate_overall_report(
        self,
        metadata: Dict[str, Any],
        languages: Dict[str, int],
        root_contents: List[Dict[str, Any]],
        contributor_count: int,
        recent_commits: List[Dict[str, Any]],
        workflow_contents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Orchestrates the full scoring report by executing all five scoring dimensions
        and consolidating the results into a single structured output.
        """
        doc_score, doc_str, doc_weak, doc_sug = self.calculate_documentation_score(root_contents)
        act_score, act_str, act_weak, act_sug = self.calculate_activity_score(metadata, recent_commits)
        org_score, org_str, org_weak, org_sug = self.calculate_organization_score(root_contents)
        com_score, com_str, com_weak, com_sug = self.calculate_community_score(metadata, contributor_count)
        mnt_score, mnt_str, mnt_weak, mnt_sug = self.calculate_maintainability_score(metadata, workflow_contents)

        breakdown = {
            "documentation": doc_score,
            "activity": act_score,
            "organization": org_score,
            "community": com_score,
            "maintainability": mnt_score
        }

        overall_score = min(100, doc_score + act_score + org_score + com_score + mnt_score)

        return {
            "overall_score": overall_score,
            "breakdown": breakdown,
            "strengths": doc_str + act_str + org_str + com_str + mnt_str,
            "weaknesses": doc_weak + act_weak + org_weak + com_weak + mnt_weak,
            "suggestions": doc_sug + act_sug + org_sug + com_sug + mnt_sug
        }
