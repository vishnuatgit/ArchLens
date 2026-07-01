import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from app.services.github_service import (
    GitHubService,
    parse_github_url,
    GitHubAPIError,
    GitHubNotFoundError,
    GitHubRateLimitError
)

# Configure AnyIO test backend
@pytest.fixture
def anyio_backend():
    return 'asyncio'

def test_parse_github_url():
    # Valid URL patterns
    assert parse_github_url("https://github.com/vishnuatgit/ArchLens") == ("vishnuatgit", "ArchLens")
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
    mock_data = {"name": "ArchLens", "owner": {"login": "vishnuatgit"}, "stargazers_count": 10}
    
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
            timeout=10.0
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
            "X-RateLimit-Reset": "1600000000"
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
            response=mock_response_fail
        )
        mock_response_fail.headers = {"X-RateLimit-Remaining": "60"}

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = mock_data
        mock_response_success.headers = {"X-RateLimit-Remaining": "60"}
        
        mock_request.side_effect = [mock_response_fail, mock_response_fail, mock_response_success]
        
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
