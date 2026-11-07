import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import httpx
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
from app.services.dependency_service import DependencyScan, scan_dependencies
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

# Receives progress events while an analysis runs (see AnalysisService.run)
ProgressCallback = Callable[[dict[str, Any]], None]

# The six GitHub calls of an analysis, named as they appear in "fetch" progress events
GITHUB_CALLS = ("metadata", "languages", "contributors", "root_files", "commits", "workflows")

T = TypeVar("T")


async def gather_or_cancel(*requests: Awaitable[Any]) -> list[Any]:
    """
    Runs the requests concurrently, like asyncio.gather, but cancels the ones still
    running as soon as one fails: after a 404 there is no point spending GitHub quota
    on the other calls.
    """
    tasks = [asyncio.ensure_future(request) for request in requests]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        raise


class AnalysisService:
    """
    Orchestrates the full repository analysis workflow:
      1. Validates and normalises the GitHub URL and repository profile.
      2. Reuses a recent report of the same repository when one exists.
      3. Fetches all required repository data from the GitHub API **concurrently**
         (a failed call cancels the rest).
      4. Calculates the overall engineering score and recommendations.
      5. Persists the results to the database, remembering the old name of a renamed repo.
      6. Returns the structured analysis report.

    run() can report each step to a progress callback; the streaming endpoint
    (POST /api/v1/analyze/stream) forwards those events to the browser.
    """

    def __init__(
        self,
        cache_ttl: timedelta | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        osv_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.github = GitHubService()
        self.metrics = MetricsService()
        self.repository_service = RepositoryService()
        # Both are optional so the CLI and scripts always run a fresh, unlimited analysis
        self.cache_ttl = cache_ttl
        self.rate_limiter = rate_limiter
        # Tests pass a client with a fake transport; None means a real one per OSV check
        self.osv_client = osv_client

    async def run(
        self,
        db: Session,
        url: str,
        repo_type: str = "library",
        client_id: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict:
        """
        Executes a complete repository analysis and persists the result.

        Args:
            db: Active SQLAlchemy session.
            url: Public GitHub repository URL or "owner/repo".
            repo_type: One of 'library', 'personal', or 'enterprise'.
            client_id: Identifies the caller (e.g. IP address) for the rate limiter.
            progress: Optional callback that receives {"event": "progress", "step", "status",
                ...details} as the analysis moves through its steps: validate, reuse (only when
                a recent report is reused), fetch (once per finished GitHub call), dependencies, analyze,
                score and save.

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

        def report(step: str, status: str = "done", **details: Any) -> None:
            if progress is not None:
                progress({"event": "progress", "step": step, "status": status, **details})

        # Step 1: Parse and validate the GitHub URL and profile
        owner, repo_name = parse_github_url(url)
        if not owner or not repo_name:
            raise InvalidRepositoryURLError(url)

        allowed_types = [t.value for t in RepoType]
        if repo_type not in allowed_types:
            raise InvalidRepoTypeError(str(repo_type), allowed_types)
        repo_type = RepoType(repo_type).value
        report("validate", repository=f"{owner}/{repo_name}", profile=repo_type)

        # Step 2: Reuse a recent report instead of spending GitHub API quota again
        if self.cache_ttl:
            now = datetime.now(UTC).replace(tzinfo=None)
            recent = self.repository_service.find_recent_analysis(
                db, canonical_github_url(owner, repo_name), repo_type, now - self.cache_ttl
            )
            if recent:
                logger.info(f"Reusing analysis id={recent.id} for {owner}/{repo_name}")
                age_seconds = max(0, int((now - recent.created_at).total_seconds()))
                report("reuse", analysis_id=recent.id, age_seconds=age_seconds)
                return self._result_from_analysis(recent)

        # Reused reports are free; every new analysis counts towards the per-client quota,
        # except one that fails because GitHub is down or out of quota (refunded below)
        counted = False
        if self.rate_limiter and client_id:
            retry_after = self.rate_limiter.hit(client_id)
            if retry_after is not None:
                raise TooManyAnalysesError(
                    self.rate_limiter.max_events,
                    int(self.rate_limiter.window_seconds),
                    retry_after,
                )
            counted = True

        def refund() -> None:
            if counted:
                self.rate_limiter.refund(client_id)

        logger.info(f"Starting analysis for {owner}/{repo_name}")
        finished_calls = 0

        async def tracked(call: str, request: Awaitable[T]) -> T:
            """Awaits one GitHub call, then reports how many of the six have finished."""
            nonlocal finished_calls
            result = await request
            finished_calls += 1
            done = finished_calls == len(GITHUB_CALLS)
            report(
                "fetch",
                "done" if done else "running",
                call=call,
                completed=finished_calls,
                total=len(GITHUB_CALLS),
            )
            return result

        try:
            # Step 3: Fetch repository data **concurrently** from GitHub API
            since_date = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            report("fetch", "running", completed=0, total=len(GITHUB_CALLS))
            requests = (
                self.github.fetch_repo_metadata(owner, repo_name),
                self.github.fetch_languages(owner, repo_name),
                self.github.fetch_contributors(owner, repo_name),
                self.github.fetch_contents(owner, repo_name, ""),
                self.github.fetch_recent_commits(owner, repo_name, since_iso=since_date),
                self.github.fetch_contents(owner, repo_name, ".github/workflows"),
            )
            (
                metadata,
                languages,
                contributors,
                root_contents,
                recent_commits,
                workflow_contents,
            ) = await gather_or_cancel(
                *(tracked(call, req) for call, req in zip(GITHUB_CALLS, requests, strict=True))
            )

        except GitHubNotFoundError:
            raise RepositoryNotFoundError(owner, repo_name)
        except GitHubEmptyRepositoryError:
            raise EmptyRepositoryError(owner, repo_name)
        except GitHubRateLimitError as e:
            refund()
            raise RateLimitExceededError(reset_epoch=e.reset_time) from e
        except GitHubAPIError as e:
            refund()
            if e.status_code == 401:
                logger.error("GitHub rejected the configured GITHUB_TOKEN (401); check the token")
            logger.error(f"GitHub API error while analyzing {owner}/{repo_name}: {e}")
            detail = f"HTTP {e.status_code}" if e.status_code else "network error"
            raise UpstreamServiceError(detail) from e

        # Step 3b: list the dependencies and check them against OSV.dev. This never fails
        # the analysis: whatever cannot be read or checked is recorded in the scan instead
        report("dependencies", "running")
        try:
            dependency_scan = await scan_dependencies(
                self.github, owner, repo_name, root_contents, self.osv_client
            )
        except Exception:
            logger.exception(f"Dependency scan crashed for {owner}/{repo_name}")
            dependency_scan = DependencyScan(
                status="error", notes=["The dependency scan failed unexpectedly."]
            )
        report(
            "dependencies",
            dependencies=len(dependency_scan.dependencies),
            vulnerabilities=len(dependency_scan.vulnerabilities),
            vulnerability_check=dependency_scan.vulnerability_check,
        )

        # GitHub reports the canonical owner/name casing and follows renames
        requested_url = canonical_github_url(owner, repo_name)
        full_name = metadata.get("full_name") if isinstance(metadata, dict) else None
        if isinstance(full_name, str) and full_name.count("/") == 1:
            owner, repo_name = full_name.split("/")

        contributor_count = len(contributors)

        # Step 4: Check the seven dimensions and calculate the score
        report("analyze", "running")
        scored = self.metrics.calculate_overall_report(
            metadata=metadata,
            languages=languages,
            root_contents=root_contents,
            contributor_count=contributor_count,
            recent_commits=recent_commits,
            workflow_contents=workflow_contents,
            repo_type=repo_type,
        )
        report("analyze", findings=len(scored["strengths"]) + len(scored["weaknesses"]))

        overall_score = scored["overall_score"]
        report("score", score=overall_score, grade=scored["health_grade"])
        duration = round(time.perf_counter() - start_time, 3)

        logger.info(
            f"Analysis complete for {owner}/{repo_name} | Score: {overall_score} | Duration: {duration}s"
        )

        # Step 5: Persist results to database inside a transaction
        try:
            db_repo = self.repository_service.get_or_create_repository(
                db=db, owner=owner, name=repo_name, url=canonical_github_url(owner, repo_name)
            )
            # Lets the old name of a renamed repository find this report later
            self.repository_service.record_rename(db, db_repo, requested_url)
            analysis = self.repository_service.save_analysis(
                db=db,
                repository_id=db_repo.id,
                score=overall_score,
                duration=duration,
                metadata=metadata,
                languages=languages,
                contributor_count=contributor_count,
                recent_commits=recent_commits,
                report=scored,
                repo_type=repo_type,
                dependency_scan=dependency_scan,
            )
        except Exception as e:
            logger.error(f"Failed to persist analysis for {owner}/{repo_name}: {e}")
            raise PersistenceError(
                f"Failed to save analysis results for {owner}/{repo_name}."
            ) from e
        report("save", analysis_id=analysis.id, suggestions=len(scored["suggestions"]))

        # Step 6: Return structured response
        return {
            "analysis_id": analysis.id,
            "status": "completed",
            "owner": owner,
            "name": repo_name,
            "repo_type": repo_type,
            "score": overall_score,
            "duration": duration,
            "breakdown": scored["breakdown"],
            "strengths": scored["strengths"],
            "weaknesses": scored["weaknesses"],
            "suggestions": scored["suggestions"],
            "dependency_scan": dependency_scan.to_dict(),
            "reused": False,
        }

    @staticmethod
    def _result_from_analysis(analysis: Analysis) -> dict:
        """Builds the run() result from a stored analysis that is being reused."""
        metrics = analysis.metrics
        scan = DependencyScan.from_json(metrics.dependencies_json) if metrics else None
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
            "dependency_scan": scan.to_dict() if scan else None,
            "reused": True,
        }
