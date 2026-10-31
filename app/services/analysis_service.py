import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.exceptions import (
    EmptyRepositoryError,
    InvalidRepositoryURLError,
    InvalidRepoTypeError,
    PersistenceError,
    RateLimitExceededError,
    RepositoryNotFoundError,
    TooManyAnalysesError,
    UpstreamServiceError,
)
from app.models.db_models import Analysis
from app.services.github_service import (
    GitHubAPIError,
    GitHubEmptyRepositoryError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubService,
    canonical_github_url,
    parse_github_url,
)
from app.services.metrics_service import MetricsService, RepoType
from app.services.rate_limiter import SlidingWindowRateLimiter
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.analysis_service")


class AnalysisService:
    """
    Orchestrates the full repository analysis workflow:
      1. Validates and normalises the GitHub URL and repository profile.
      2. Reuses a recent report of the same repository when one exists.
      3. Fetches all required repository data from the GitHub API **concurrently**.
      4. Calculates the overall engineering score and recommendations.
      5. Persists the results to the database.
      6. Returns the structured analysis report.
    """

    def __init__(
        self,
        cache_ttl: timedelta | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self.github = GitHubService()
        self.metrics = MetricsService()
        self.repository_service = RepositoryService()
        # Both are optional so the CLI and scripts always run a fresh, unlimited analysis
        self.cache_ttl = cache_ttl
        self.rate_limiter = rate_limiter

    async def run(
        self,
        db: Session,
        url: str,
        repo_type: str = "library",
        client_id: str | None = None,
    ) -> dict:
        """
        Executes a complete repository analysis and persists the result.

        Args:
            db: Active SQLAlchemy session.
            url: Public GitHub repository URL or "owner/repo".
            repo_type: One of 'library', 'personal', or 'enterprise'.
            client_id: Identifies the caller (e.g. IP address) for the rate limiter.

        Returns:
            Dict with analysis_id, score, breakdown, strengths, weaknesses, suggestions,
            and `reused` (True when a recent report was returned instead of a new one).

        Raises:
            InvalidRepositoryURLError: If the URL cannot be parsed.
            InvalidRepoTypeError: If the profile is not supported.
            TooManyAnalysesError: If the client exceeded its analysis quota.
            RepositoryNotFoundError: If the repo does not exist on GitHub.
            EmptyRepositoryError: If the repo has no commits yet.
            RateLimitExceededError: If the GitHub API rate limit is hit.
            UpstreamServiceError: If GitHub fails or cannot be reached.
            PersistenceError: If database write fails.
        """
        start_time = time.perf_counter()

        # Step 1: Parse and validate the GitHub URL and profile
        owner, repo_name = parse_github_url(url)
        if not owner or not repo_name:
            raise InvalidRepositoryURLError(url)

        allowed_types = [t.value for t in RepoType]
        if repo_type not in allowed_types:
            raise InvalidRepoTypeError(str(repo_type), allowed_types)
        repo_type = RepoType(repo_type).value

        # Step 2: Reuse a recent report instead of spending GitHub API quota again
        if self.cache_ttl:
            since = datetime.now(UTC).replace(tzinfo=None) - self.cache_ttl
            recent = self.repository_service.find_recent_analysis(
                db, canonical_github_url(owner, repo_name), repo_type, since
            )
            if recent:
                logger.info(f"Reusing analysis id={recent.id} for {owner}/{repo_name}")
                return self._result_from_analysis(recent)

        # Only analyses that reach GitHub count towards the per-client quota
        if self.rate_limiter and client_id:
            retry_after = self.rate_limiter.hit(client_id)
            if retry_after is not None:
                raise TooManyAnalysesError(
                    self.rate_limiter.max_events,
                    int(self.rate_limiter.window_seconds),
                    retry_after,
                )

        logger.info(f"Starting analysis for {owner}/{repo_name}")

        try:
            # Step 3: Fetch repository data **concurrently** from GitHub API
            since_date = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

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
        except GitHubEmptyRepositoryError:
            raise EmptyRepositoryError(owner, repo_name)
        except GitHubRateLimitError as e:
            raise RateLimitExceededError(reset_epoch=e.reset_time) from e
        except GitHubAPIError as e:
            if e.status_code == 401:
                logger.error("GitHub rejected the configured GITHUB_TOKEN (401); check the token")
            logger.error(f"GitHub API error while analyzing {owner}/{repo_name}: {e}")
            detail = f"HTTP {e.status_code}" if e.status_code else "network error"
            raise UpstreamServiceError(detail) from e

        # GitHub reports the canonical owner/name casing and follows renames
        full_name = metadata.get("full_name") if isinstance(metadata, dict) else None
        if isinstance(full_name, str) and full_name.count("/") == 1:
            owner, repo_name = full_name.split("/")

        contributor_count = len(contributors)

        # Step 4: Calculate the full scoring report
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

        # Step 5: Persist results to database inside a transaction
        try:
            db_repo = self.repository_service.get_or_create_repository(
                db=db, owner=owner, name=repo_name, url=canonical_github_url(owner, repo_name)
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

        # Step 6: Return structured response
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
            "reused": False,
        }

    @staticmethod
    def _result_from_analysis(analysis: Analysis) -> dict:
        """Builds the run() result from a stored analysis that is being reused."""
        metrics = analysis.metrics
        return {
            "analysis_id": analysis.id,
            "status": "completed",
            "owner": analysis.repository.owner,
            "name": analysis.repository.name,
            "repo_type": analysis.repo_type,
            "score": analysis.score,
            "duration": analysis.duration,
            "breakdown": json.loads(metrics.score_breakdown_json or "{}") if metrics else {},
            "strengths": json.loads(metrics.strengths_json or "[]") if metrics else [],
            "weaknesses": json.loads(metrics.weaknesses_json or "[]") if metrics else [],
            "suggestions": json.loads(metrics.suggestions_json or "[]") if metrics else [],
            "reused": True,
        }
