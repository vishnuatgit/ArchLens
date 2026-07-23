import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.exceptions import (
    InvalidRepositoryURLError,
    PersistenceError,
    RateLimitExceededError,
    RepositoryNotFoundError,
)
from app.services.github_service import (
    GitHubService,
    GitHubNotFoundError,
    GitHubRateLimitError,
    parse_github_url,
)
from app.services.metrics_service import MetricsService
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.analysis_service")


class AnalysisService:
    """
    Orchestrates the full repository analysis workflow:
      1. Validates and parses the GitHub URL.
      2. Fetches all required repository data from the GitHub API **concurrently**.
      3. Calculates the overall engineering score and recommendations.
      4. Persists the results to the database.
      5. Returns the structured analysis report.
    """

    def __init__(self) -> None:
        self.github = GitHubService()
        self.metrics = MetricsService()
        self.repository_service = RepositoryService()

    async def run(self, db: Session, url: str, repo_type: str = "library") -> dict:
        """
        Executes a complete repository analysis and persists the result.

        Args:
            db: Active SQLAlchemy session.
            url: Public GitHub repository URL.
            repo_type: One of 'library', 'personal', or 'enterprise'.

        Returns:
            Dict with analysis_id, score, breakdown, strengths, weaknesses, suggestions.

        Raises:
            InvalidRepositoryURLError: If the URL cannot be parsed.
            RepositoryNotFoundError: If the repo does not exist on GitHub.
            RateLimitExceededError: If the GitHub API rate limit is hit.
            PersistenceError: If database write fails.
        """
        start_time = time.perf_counter()

        # Step 1: Parse and validate the GitHub URL
        owner, repo_name = parse_github_url(url)
        if not owner or not repo_name:
            raise InvalidRepositoryURLError(url)

        logger.info(f"Starting analysis for {owner}/{repo_name}")

        try:
            # Step 2: Fetch repository data **concurrently** from GitHub API
            since_date = (
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            (
                metadata,
                languages,
                contributors,
                root_contents,
                recent_commits,
                workflow_contents,
            ) = await asyncio.gather(
                self.github.fetch_repo_metadata(owner, repo_name),
                self.github.fetch_languages(owner, repo_name),
                self.github.fetch_contributors(owner, repo_name),
                self.github.fetch_contents(owner, repo_name, ""),
                self.github.fetch_recent_commits(owner, repo_name, since_iso=since_date),
                self.github.fetch_contents(owner, repo_name, ".github/workflows"),
            )

        except GitHubNotFoundError:
            raise RepositoryNotFoundError(owner, repo_name)
        except GitHubRateLimitError as e:
            raise RateLimitExceededError(reset_epoch=e.reset_time) from e

        contributor_count = len(contributors)

        # Step 3: Calculate the full scoring report
        report = self.metrics.calculate_overall_report(
            metadata=metadata,
            languages=languages,
            root_contents=root_contents,
            contributor_count=contributor_count,
            recent_commits=recent_commits,
            workflow_contents=workflow_contents,
            repo_type=repo_type,
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
                repo_type=repo_type,
            )
        except Exception as e:
            logger.error(f"Failed to persist analysis for {owner}/{repo_name}: {e}")
            raise PersistenceError(
                f"Failed to save analysis results for {owner}/{repo_name}."
            ) from e

        # Step 5: Return structured response
        return {
            "analysis_id": analysis.id,
            "status": "completed",
            "owner": owner,
            "name": repo_name,
            "repo_type": repo_type,
            "score": overall_score,
            "duration": duration,
            "breakdown": report["breakdown"],
            "strengths": report["strengths"],
            "weaknesses": report["weaknesses"],
            "suggestions": report["suggestions"],
        }
