import logging
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
        Evaluates repository activity (Max: 20 points). Placeholder.
        """
        return 0, [], [], []

    def calculate_organization_score(self, root_contents: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Evaluates repository code structure and configuration files (Max: 20 points). Placeholder.
        """
        return 0, [], [], []

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
        Orchestrates full scoring report calculation.
        """
        doc_score, doc_str, doc_weak, doc_sug = self.calculate_documentation_score(root_contents)

        breakdown = {
            "documentation": doc_score,
            "activity": 0,
            "organization": 0,
            "community": 0,
            "maintainability": 0
        }

        overall_score = doc_score

        return {
            "overall_score": overall_score,
            "breakdown": breakdown,
            "strengths": doc_str,
            "weaknesses": doc_weak,
            "suggestions": doc_sug
        }
