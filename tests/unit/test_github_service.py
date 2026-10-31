from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.github_service import (
    GitHubAPIError,
    GitHubEmptyRepositoryError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubService,
    canonical_github_url,
    parse_github_url,
)


# Configure AnyIO test backend
@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_parse_github_url():
    # Valid URL patterns
    assert parse_github_url("https://github.com/vishnuatgit/ArchLens") == (
        "vishnuatgit",
        "ArchLens",
    )
    assert parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")
    assert parse_github_url("http://github.com/owner/repo/") == ("owner", "repo")
    assert parse_github_url("github.com/owner/repo") == ("owner", "repo")

    # Invalid patterns
    assert parse_github_url("https://github.com/owner") == (None, None)
    assert parse_github_url("https://google.com") == (None, None)
    assert parse_github_url("") == (None, None)
    assert parse_github_url(None) == (None, None)


@pytest.mark.anyio
async def test_fetch_repo_metadata_success():
    service = GitHubService(token="fake-token")
    mock_data = {
        "name": "ArchLens",
        "owner": {"login": "vishnuatgit"},
        "stargazers_count": 10,
    }

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data
        mock_response.headers = {"X-RateLimit-Remaining": "4999"}
        mock_request.return_value = mock_response

        result = await service.fetch_repo_metadata("vishnuatgit", "ArchLens")
        assert result == mock_data
        mock_request.assert_called_once_with(
            "GET",
            "https://api.github.com/repos/vishnuatgit/ArchLens",
            headers=service.headers,
            params=None,
            timeout=10.0,
        )


@pytest.mark.anyio
async def test_fetch_repo_metadata_not_found():
    service = GitHubService()

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"X-RateLimit-Remaining": "59"}
        mock_request.return_value = mock_response

        with pytest.raises(GitHubNotFoundError):
            await service.fetch_repo_metadata("owner", "nonexistent")


@pytest.mark.anyio
async def test_fetch_repo_metadata_rate_limit():
    service = GitHubService()

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1600000000",
        }
        mock_request.return_value = mock_response

        with pytest.raises(GitHubRateLimitError) as exc_info:
            await service.fetch_repo_metadata("owner", "repo")
        assert exc_info.value.reset_time == 1600000000


@pytest.mark.anyio
async def test_make_request_transient_error_retry():
    service = GitHubService()
    mock_data = {"status": "ok"}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        # Mock 2 transient status code errors followed by 1 successful response
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 503
        mock_response_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="Service Unavailable",
            request=MagicMock(),
            response=mock_response_fail,
        )
        mock_response_fail.headers = {"X-RateLimit-Remaining": "60"}

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = mock_data
        mock_response_success.headers = {"X-RateLimit-Remaining": "60"}

        mock_request.side_effect = [
            mock_response_fail,
            mock_response_fail,
            mock_response_success,
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await service._make_request("GET", "/test")
            assert result == mock_data
            assert mock_request.call_count == 3
            assert mock_sleep.call_count == 2


@pytest.mark.anyio
async def test_fetch_contributors_empty_repo():
    service = GitHubService()

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_response = MagicMock()
        # Empty repo can return HTTP 204 No Content
        mock_response.status_code = 204
        mock_response.headers = {"X-RateLimit-Remaining": "60"}
        mock_request.return_value = mock_response

        result = await service.fetch_contributors("owner", "empty-repo")
        assert result == []


@pytest.mark.anyio
async def test_fetch_contents_not_found():
    service = GitHubService()

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"X-RateLimit-Remaining": "60"}
        mock_request.return_value = mock_response

        result = await service.fetch_contents("owner", "repo", "tests/nonexistent-folder")
        assert result == []


def test_parse_github_url_normalises_variants():
    # Trailing slash, .git, www., scheme-less, extra path segments and bare owner/repo
    for url in [
        "https://github.com/psf/requests/",
        "https://github.com/psf/requests.git",
        "https://www.github.com/psf/requests",
        "HTTPS://GITHUB.COM/psf/requests",
        "github.com/psf/requests/tree/main/src",
        "https://github.com/psf/requests?tab=readme-ov-file",
        "  psf/requests  ",
    ]:
        assert parse_github_url(url) == ("psf", "requests"), url


def test_parse_github_url_rejects_unsafe_names():
    for url in [
        "psf",
        "psf/requests/extra",
        "../..",
        "https://github.com/psf/..",
        "https://github.com/psf/re quests",
        "https://gitlab.com/psf/requests",
        "https://github.com/psf%2F/requests",
    ]:
        assert parse_github_url(url) == (None, None), url


def test_canonical_github_url():
    assert canonical_github_url("psf", "requests") == "https://github.com/psf/requests"


def _service_with_responses(*responses: httpx.Response) -> tuple[GitHubService, list[str]]:
    """Builds a service whose shared client answers from a fixed list of responses."""
    queue = list(responses)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return queue.pop(0)

    service = GitHubService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return service, seen


@pytest.mark.anyio
async def test_status_429_is_a_rate_limit_with_retry_after():
    service, _ = _service_with_responses(httpx.Response(429, headers={"Retry-After": "120"}))

    with pytest.raises(GitHubRateLimitError) as exc_info:
        await service.fetch_repo_metadata("owner", "repo")
    assert exc_info.value.status_code == 429
    assert exc_info.value.reset_time is not None


@pytest.mark.anyio
async def test_secondary_rate_limit_403_is_detected_from_message():
    service, _ = _service_with_responses(
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit."})
    )

    with pytest.raises(GitHubRateLimitError):
        await service.fetch_repo_metadata("owner", "repo")


@pytest.mark.anyio
async def test_status_409_on_commits_means_empty_repository():
    service, _ = _service_with_responses(
        httpx.Response(409, json={"message": "Git Repository is empty."})
    )

    with pytest.raises(GitHubEmptyRepositoryError):
        await service.fetch_recent_commits("owner", "empty", since_iso="2026-01-01T00:00:00Z")


@pytest.mark.anyio
async def test_unexpected_status_raises_api_error_with_status_code():
    service, _ = _service_with_responses(httpx.Response(401, json={"message": "Bad credentials"}))

    with pytest.raises(GitHubAPIError) as exc_info:
        await service.fetch_repo_metadata("owner", "repo")
    assert exc_info.value.status_code == 401
    assert not isinstance(exc_info.value, GitHubRateLimitError)


@pytest.mark.anyio
async def test_requests_share_one_client_until_closed():
    service, seen = _service_with_responses(
        httpx.Response(200, json={"full_name": "owner/repo"}),
        httpx.Response(200, json={"Python": 10}),
    )
    client = service.client

    await service.fetch_repo_metadata("owner", "repo")
    await service.fetch_languages("owner", "repo")

    assert service.client is client
    assert seen == ["/repos/owner/repo", "/repos/owner/repo/languages"]

    await service.aclose()
    assert client.is_closed
    assert service._client is None


@pytest.mark.anyio
async def test_start_opens_client_once():
    service = GitHubService()
    service.start()
    client = service.client
    service.start()
    assert service.client is client
    await service.aclose()
