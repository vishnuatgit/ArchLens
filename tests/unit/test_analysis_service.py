from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import (
    EmptyRepositoryError,
    InvalidRepoTypeError,
    RateLimitExceededError,
    RepositoryNotFoundError,
    TooManyAnalysesError,
    UpstreamServiceError,
)
from app.services.analysis_service import AnalysisService
from app.services.github_service import (
    GitHubAPIError,
    GitHubEmptyRepositoryError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from app.services.rate_limiter import SlidingWindowRateLimiter


@pytest.fixture
def analysis_service():
    return AnalysisService()


@pytest.mark.asyncio
async def test_analysis_run(analysis_service):
    with (
        patch(
            "app.services.github_service.GitHubService.fetch_repo_metadata", new_callable=AsyncMock
        ) as mock_meta,
        patch(
            "app.services.github_service.GitHubService.fetch_languages", new_callable=AsyncMock
        ) as mock_langs,
        patch(
            "app.services.github_service.GitHubService.fetch_contents", new_callable=AsyncMock
        ) as mock_dir,
        patch(
            "app.services.github_service.GitHubService.fetch_contributors", new_callable=AsyncMock
        ) as mock_contributors,
        patch(
            "app.services.github_service.GitHubService.fetch_recent_commits", new_callable=AsyncMock
        ) as mock_commits,
        patch(
            "app.services.repository_service.RepositoryService.get_or_create_repository"
        ) as mock_get_repo,
        patch("app.services.repository_service.RepositoryService.save_analysis") as mock_save,
    ):

        mock_meta.return_value = {
            "stargazers_count": 100,
            "updated_at": "2023-01-01T00:00:00Z",
            "size": 1000,
            "has_wiki": True,
        }
        mock_langs.return_value = {"Python": 1000}
        mock_contributors.return_value = [{"login": "alice"}, {"login": "bob"}]
        mock_dir.return_value = [{"name": "README.md", "type": "file"}]
        mock_commits.return_value = [{"sha": "123", "commit": {"author": {"name": "test"}}}]

        mock_repo = MagicMock()
        mock_repo.id = 1
        mock_get_repo.return_value = mock_repo

        mock_analysis = MagicMock()
        mock_analysis.id = 1
        mock_save.return_value = mock_analysis

        db = MagicMock()

        result = await analysis_service.run(db, "https://github.com/test/test", "library")

        assert "score" in result
        assert result["owner"] == "test"
        assert result["name"] == "test"
        assert result["analysis_id"] == 1
        assert "breakdown" in result


def _stub_github(service: AnalysisService, metadata: dict | None = None, error=None) -> None:
    """Replaces every GitHub fetch with a stub; `error` is raised by the commits call."""
    github = MagicMock()
    github.fetch_repo_metadata = AsyncMock(return_value=metadata or {"pushed_at": None})
    github.fetch_languages = AsyncMock(return_value={"Python": 100})
    github.fetch_contributors = AsyncMock(return_value=[])
    github.fetch_contents = AsyncMock(return_value=[])
    github.fetch_recent_commits = AsyncMock(side_effect=error, return_value=[])
    service.github = github


def _stub_persistence(service: AnalysisService, analysis_id: int = 7) -> MagicMock:
    repo_svc = MagicMock()
    repo_svc.get_or_create_repository.return_value = MagicMock(id=1)
    repo_svc.save_analysis.return_value = MagicMock(id=analysis_id)
    repo_svc.find_recent_analysis.return_value = None
    service.repository_service = repo_svc
    return repo_svc


@pytest.mark.asyncio
async def test_invalid_repo_type_is_rejected_before_calling_github():
    service = AnalysisService()
    _stub_github(service)

    with pytest.raises(InvalidRepoTypeError):
        await service.run(MagicMock(), "psf/requests", "banana")
    service.github.fetch_repo_metadata.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("github_error", "expected"),
    [
        (GitHubNotFoundError("missing"), RepositoryNotFoundError),
        (GitHubEmptyRepositoryError("empty"), EmptyRepositoryError),
        (GitHubRateLimitError("limited", reset_time=1), RateLimitExceededError),
        (GitHubAPIError("Bad credentials", status_code=401), UpstreamServiceError),
        (GitHubAPIError("Network error connecting to GitHub"), UpstreamServiceError),
    ],
)
async def test_github_errors_map_to_application_errors(github_error, expected):
    service = AnalysisService()
    _stub_github(service, error=github_error)

    with pytest.raises(expected) as exc_info:
        await service.run(MagicMock(), "owner/repo", "library")
    assert exc_info.value.status_code in {404, 422, 502, 503}


@pytest.mark.asyncio
async def test_repository_is_stored_under_canonical_url():
    service = AnalysisService()
    _stub_github(service, metadata={"full_name": "psf/requests", "pushed_at": None})
    repo_svc = _stub_persistence(service)

    result = await service.run(MagicMock(), "https://www.github.com/PSF/Requests.git/", "library")

    repo_svc.get_or_create_repository.assert_called_once()
    kwargs = repo_svc.get_or_create_repository.call_args.kwargs
    assert kwargs["url"] == "https://github.com/psf/requests"
    assert (kwargs["owner"], kwargs["name"]) == ("psf", "requests")
    assert result["reused"] is False


@pytest.mark.asyncio
async def test_recent_analysis_is_reused_without_calling_github():
    service = AnalysisService(cache_ttl=timedelta(minutes=60))
    _stub_github(service)
    repo_svc = _stub_persistence(service)
    recent = MagicMock(id=42, score=80, duration=1.0, repo_type="library")
    recent.repository.owner, recent.repository.name = "psf", "requests"
    recent.metrics.score_breakdown_json = '{"documentation": 15}'
    recent.metrics.strengths_json = recent.metrics.weaknesses_json = "[]"
    recent.metrics.suggestions_json = "[]"
    repo_svc.find_recent_analysis.return_value = recent

    result = await service.run(MagicMock(), "github.com/psf/requests/", "library")

    assert result["analysis_id"] == 42
    assert result["reused"] is True
    assert result["breakdown"] == {"documentation": 15}
    url_arg = repo_svc.find_recent_analysis.call_args.args[1]
    assert url_arg == "https://github.com/psf/requests"
    service.github.fetch_repo_metadata.assert_not_called()


@pytest.mark.asyncio
async def test_per_client_limit_only_counts_analyses_that_reach_github():
    service = AnalysisService(
        cache_ttl=timedelta(minutes=60),
        rate_limiter=SlidingWindowRateLimiter(max_events=1, window_seconds=600),
    )
    _stub_github(service)
    repo_svc = _stub_persistence(service)

    await service.run(MagicMock(), "owner/one", "library", client_id="1.2.3.4")

    # A cache hit is free...
    repo_svc.find_recent_analysis.return_value = MagicMock(id=1, metrics=None)
    reused = await service.run(MagicMock(), "owner/one", "library", client_id="1.2.3.4")
    assert reused["reused"] is True

    # ...but a second fresh analysis from the same client is refused
    repo_svc.find_recent_analysis.return_value = None
    with pytest.raises(TooManyAnalysesError) as exc_info:
        await service.run(MagicMock(), "owner/two", "library", client_id="1.2.3.4")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds > 0

    # Other clients are unaffected
    await service.run(MagicMock(), "owner/two", "library", client_id="5.6.7.8")
