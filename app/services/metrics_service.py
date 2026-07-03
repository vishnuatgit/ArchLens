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
        Evaluates repository community engagement metrics (Max: 20 points). Placeholder.
        """
        return 0, [], [], []

    def calculate_maintainability_score(self, metadata: Dict[str, Any], workflow_contents: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository maintenance and test configuration metrics (Max: 20 points). Placeholder.
        """
        return 0, [], [], []

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
        Orchestrates full scoring report calculation by executing all scoring dimensions.
        """
        doc_score, doc_str, doc_weak, doc_sug = self.calculate_documentation_score(root_contents)
        act_score, act_str, act_weak, act_sug = self.calculate_activity_score(metadata, recent_commits)
        org_score, org_str, org_weak, org_sug = self.calculate_organization_score(root_contents)

        breakdown = {
            "documentation": doc_score,
            "activity": act_score,
            "organization": org_score,
            "community": 0,
            "maintainability": 0
        }

        # Consolidate all metrics (remaining 40 pts are placeholders)
        overall_score = doc_score + act_score + org_score

        strengths = doc_str + act_str + org_str
        weaknesses = doc_weak + act_weak + org_weak
        suggestions = doc_sug + act_sug + org_sug

        return {
            "overall_score": overall_score,
            "breakdown": breakdown,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "suggestions": suggestions
        }
