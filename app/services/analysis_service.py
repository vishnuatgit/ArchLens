import logging
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.services.github_service import (
    GitHubService,
    parse_github_url,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from app.services.metrics_service import MetricsService
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.analysis_service")


class AnalysisService:
    """
    Orchestrates the full repository analysis workflow:
      1. Validates and parses the GitHub URL
      2. Fetches all required repository data from the GitHub API
      3. Calculates the overall engineering score and recommendations
      4. Persists the results to the database
      5. Returns the structured analysis report
    """

    def __init__(self):
        self.github = GitHubService()
        self.metrics = MetricsService()
        self.repository_service = RepositoryService()

    async def run(self, db: Session, url: str) -> dict:
        """
        Executes a complete repository analysis and persists the result.
        Returns a dict with analysis_id, score, breakdown, strengths, weaknesses, suggestions.
        """
        start_time = time.perf_counter()

        # Step 1: Parse and validate the GitHub URL
        owner, repo_name = parse_github_url(url)
        if not owner or not repo_name:
            raise ValueError(f"Invalid or unsupported GitHub repository URL: {url}")

        logger.info(f"Starting analysis for {owner}/{repo_name}")

        try:
            # Step 2: Fetch repository data concurrently from GitHub API
            since_date = (
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            metadata = await self.github.fetch_repo_metadata(owner, repo_name)
            languages = await self.github.fetch_languages(owner, repo_name)
            contributors = await self.github.fetch_contributors(owner, repo_name)
            root_contents = await self.github.fetch_contents(owner, repo_name, "")
            recent_commits = await self.github.fetch_recent_commits(
                owner, repo_name, since_iso=since_date
            )
            workflow_contents = await self.github.fetch_contents(
                owner, repo_name, ".github/workflows"
            )

        except GitHubNotFoundError:
            raise ValueError(
                f"Repository '{owner}/{repo_name}' was not found on GitHub."
            )
        except GitHubRateLimitError as e:
            raise RuntimeError(
                "GitHub API rate limit exceeded. Try again later."
            ) from e

        contributor_count = len(contributors)

        # Step 3: Calculate the full scoring report
        report = self.metrics.calculate_overall_report(
            metadata=metadata,
            languages=languages,
            root_contents=root_contents,
            contributor_count=contributor_count,
            recent_commits=recent_commits,
            workflow_contents=workflow_contents,
        )

        overall_score = report["overall_score"]
        duration = round(time.perf_counter() - start_time, 3)

        logger.info(
            f"Analysis complete for {owner}/{repo_name} | Score: {overall_score} | Duration: {duration}s"
        )

        # Step 4: Persist results to database inside a transaction
        try:
            db_repo = self.repository_service.get_or_create_repository(
                db=db, owner=owner, name=repo_name, url=url
            )
            analysis = self.repository_service.save_analysis(
                db=db,
                repository_id=db_repo.id,
                score=overall_score,
                duration=duration,
                metadata=metadata,
                languages=languages,
                contributor_count=contributor_count,
                recent_commits=recent_commits,
                report=report,
            )
        except Exception as e:
            logger.error(
                f"Failed to persist analysis for {owner}/{repo_name}: {str(e)}"
            )
            raise RuntimeError(
                "Failed to save analysis results to the database."
            ) from e

        # Step 5: Return structured response
        return {
            "analysis_id": analysis.id,
            "status": "completed",
            "owner": owner,
            "name": repo_name,
            "score": overall_score,
            "duration": duration,
            "breakdown": report["breakdown"],
            "strengths": report["strengths"],
            "weaknesses": report["weaknesses"],
            "suggestions": report["suggestions"],
        }
