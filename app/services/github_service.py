import re
import logging
import asyncio
from typing import Tuple, Optional, Dict, Any, List
import httpx
from app.config import settings

logger = logging.getLogger("ArchLens.github_service")

class GitHubAPIError(Exception):
    """Base exception for all GitHub API client errors."""
    pass

class GitHubNotFoundError(GitHubAPIError):
    """Exception raised when a repository, path, or resource is not found (404)."""
    pass

class GitHubRateLimitError(GitHubAPIError):
    """Exception raised when the GitHub API rate limits are hit (403)."""
    def __init__(self, message: str, reset_time: Optional[int] = None):
        super().__init__(message)
        self.reset_time = reset_time

def parse_github_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses a GitHub repository URL to extract the owner and repository name.
    Supports formats:
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
      - http://github.com/owner/repo
      - github.com/owner/repo
    """
    if not url:
        return None, None
    
    url = url.strip()
    
    # Strip trailing slash if present
    if url.endswith("/"):
        url = url[:-1]
        
    # Strip trailing .git if present
    if url.endswith(".git"):
        url = url[:-4]
        
    # Regex to capture the owner and repository name
    pattern = r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/\s\?#]+)(?:/|$)"
    match = re.search(pattern, url, re.IGNORECASE)
    if match:
        owner, repo = match.group(1), match.group(2)
        if owner and repo:
            return owner, repo
            
    return None, None

class GitHubService:
    """
    Service client to communicate asynchronously with the GitHub REST API.
    Handles rate limiting, automatic retries for transient errors, and parses responses.
    """
    def __init__(self, token: Optional[str] = None):
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ArchLens-Platform"
        }
        
        # Use provided token or fall back to application settings
        auth_token = token or settings.GITHUB_TOKEN
        if auth_token:
            self.headers["Authorization"] = f"token {auth_token}"
            logger.info("GitHub service initialized with authentication token")
        else:
            logger.warning("GitHub service initialized WITHOUT token (unauthenticated rate limits apply)")

    async def _make_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Executes an HTTP request to the GitHub API, handling rate limits and retries on transient errors.
        """
        url = f"{self.base_url}{path}"
        max_retries = 3
        backoff_factor = 1.5

        for attempt in range(max_retries):
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.request(
                        method,
                        url,
                        headers=self.headers,
                        params=params,
                        timeout=10.0
                    )

                    # Check for rate limiting
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    if response.status_code == 403 and remaining == "0":
                        reset_time = response.headers.get("X-RateLimit-Reset")
                        reset_epoch = int(reset_time) if reset_time else None
                        raise GitHubRateLimitError(
                            "GitHub API rate limit exceeded.",
                            reset_time=reset_epoch
                        )

                    # Check for Not Found
                    if response.status_code == 404:
                        raise GitHubNotFoundError(f"Resource not found: {url}")

                    response.raise_for_status()

                    # Handle 204 No Content (e.g. empty repository logs)
                    if response.status_code == 204:
                        return None

                    return response.json()

                except httpx.HTTPStatusError as e:
                    # Retry on transient server errors
                    if e.response.status_code in [500, 502, 503, 504] and attempt < max_retries - 1:
                        sleep_time = backoff_factor ** attempt
                        logger.warning(f"Transient error {e.response.status_code}. Retrying in {sleep_time:.2f}s...")
                        await asyncio.sleep(sleep_time)
                        continue
                    raise GitHubAPIError(f"HTTP error {e.response.status_code}: {e.response.text}") from e

                except httpx.RequestError as e:
                    # Retry on connection/timeout issues
                    if attempt < max_retries - 1:
                        sleep_time = backoff_factor ** attempt
                        logger.warning(f"Connection error: {str(e)}. Retrying in {sleep_time:.2f}s...")
                        await asyncio.sleep(sleep_time)
                        continue
                    raise GitHubAPIError(f"Network error connecting to GitHub: {str(e)}") from e

    async def fetch_repo_metadata(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Fetches core repository metadata.
        Endpoint: GET /repos/{owner}/{repo}
        """
        return await self._make_request("GET", f"/repos/{owner}/{repo}")

    async def fetch_languages(self, owner: str, repo: str) -> Dict[str, int]:
        """
        Fetches language breakdown for the repository in bytes.
        Endpoint: GET /repos/{owner}/{repo}/languages
        """
        return await self._make_request("GET", f"/repos/{owner}/{repo}/languages") or {}

    async def fetch_contributors(self, owner: str, repo: str, per_page: int = 100) -> List[Dict[str, Any]]:
        """
        Fetches the list of contributors for a repository.
        Endpoint: GET /repos/{owner}/{repo}/contributors
        """
        try:
            return await self._make_request(
                "GET", 
                f"/repos/{owner}/{repo}/contributors", 
                params={"per_page": per_page}
            ) or []
        except GitHubNotFoundError:
            # Empty repositories can return 404 for contributors endpoint
            return []

    async def fetch_contents(self, owner: str, repo: str, path: str = "") -> List[Dict[str, Any]]:
        """
        Fetches the contents of a directory or file in the repository (default root).
        Endpoint: GET /repos/{owner}/{repo}/contents/{path}
        """
        try:
            data = await self._make_request("GET", f"/repos/{owner}/{repo}/contents/{path}")
            if data is None:
                return []
            return data if isinstance(data, list) else [data]
        except GitHubNotFoundError:
            return []

    async def fetch_recent_commits(self, owner: str, repo: str, since_iso: str) -> List[Dict[str, Any]]:
        """
        Fetches the commits for a repository since a specific ISO 8601 date.
        Endpoint: GET /repos/{owner}/{repo}/commits
        """
        try:
            return await self._make_request(
                "GET", 
                f"/repos/{owner}/{repo}/commits", 
                params={"since": since_iso, "per_page": 100}
            ) or []
        except GitHubNotFoundError:
            return []
