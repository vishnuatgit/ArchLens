import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("ArchLens.github_service")

REQUEST_TIMEOUT = 10.0

# GitHub owner names are alphanumerics and hyphens; repository names also allow '.' and '_'.
# Restricting the characters keeps user input from reaching other API paths.
_OWNER = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
_REPO = r"[A-Za-z0-9._-]{1,100}"
_URL_PATTERN = re.compile(
    rf"^(?:https?://)?(?:www\.)?github\.com/({_OWNER})/({_REPO})(?:[/?#].*)?$", re.IGNORECASE
)
_SLUG_PATTERN = re.compile(rf"^({_OWNER})/({_REPO})$")


class GitHubAPIError(Exception):
    """Base exception for all GitHub API client errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GitHubNotFoundError(GitHubAPIError):
    """Exception raised when a repository, path, or resource is not found (404)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=404)


class GitHubEmptyRepositoryError(GitHubAPIError):
    """Exception raised when the repository has no commits yet (409 on /commits)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=409)


class GitHubRateLimitError(GitHubAPIError):
    """Exception raised when the GitHub API rate limits are hit (403 or 429)."""

    def __init__(self, message: str, reset_time: int | None = None, status_code: int = 403):
        super().__init__(message, status_code=status_code)
        self.reset_time = reset_time


def parse_github_url(url: str) -> tuple[str | None, str | None]:
    """
    Parses a GitHub repository URL to extract the owner and repository name.
    Supports formats:
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
      - http://github.com/owner/repo
      - https://www.github.com/owner/repo/tree/main
      - github.com/owner/repo
      - owner/repo
    """
    if not url:
        return None, None

    # Strip whitespace, trailing slashes and a trailing .git suffix
    url = url.strip().rstrip("/")
    if url.lower().endswith(".git"):
        url = url[:-4]

    match = _URL_PATTERN.match(url) or _SLUG_PATTERN.match(url)
    if match:
        owner, repo = match.group(1), match.group(2)
        if repo not in (".", ".."):
            return owner, repo

    return None, None


def canonical_github_url(owner: str, repo: str) -> str:
    """Returns the normalised URL under which a repository is stored."""
    return f"https://github.com/{owner}/{repo}"


def _rate_limit_reset(response: httpx.Response) -> int | None:
    """Returns the Unix time at which the rate limit resets, if GitHub reported it."""
    reset = response.headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        return int(reset)
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return int(time.time()) + int(retry_after)
    return None


def _is_rate_limited(response: httpx.Response) -> bool:
    """Detects primary (quota exhausted) and secondary (abuse) rate limit responses."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    # Secondary rate limits are a 403 that explains itself in the body
    return "rate limit" in response.text.lower()


class GitHubService:
    """
    Service client to communicate asynchronously with the GitHub REST API.
    Handles rate limiting, automatic retries for transient errors, and parses responses.

    A single shared httpx.AsyncClient is reused for every request so that the
    TLS setup cost is paid once and concurrent requests share a connection pool.
    """

    def __init__(self, token: str | None = None):
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ArchLens-Platform",
        }
        self._client: httpx.AsyncClient | None = None

        # Use provided token or fall back to application settings
        auth_token = token or settings.GITHUB_TOKEN
        if auth_token:
            self.headers["Authorization"] = f"token {auth_token}"
            logger.info("GitHub service initialized with authentication token")
        else:
            logger.warning(
                "GitHub service initialized WITHOUT token (unauthenticated rate limits apply)"
            )

    def start(self) -> None:
        """Opens the shared HTTP client. Called once from the application lifespan."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT)

    async def aclose(self) -> None:
        """Closes the shared HTTP client on application shutdown (or after a CLI run)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        # The CLI and scripts run outside the app lifespan, so open the client on first use
        if self._client is None or self._client.is_closed:
            self.start()
        return self._client

    async def _make_request(
        self, method: str, path: str, params: dict[str, Any] | None = None, raw: bool = False
    ) -> Any:
        """
        Executes an HTTP request to the GitHub API, handling rate limits and retries on transient errors.
        With raw=True the response is a file's text (GitHub's raw media type) instead of JSON.
        """
        url = f"{self.base_url}{path}"
        max_retries = 3
        backoff_factor = 1.5
        headers = (
            {**self.headers, "Accept": "application/vnd.github.raw+json"} if raw else self.headers
        )

        for attempt in range(max_retries):
            try:
                response = await self.client.request(
                    method, url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
                )

                # Check for rate limiting
                if _is_rate_limited(response):
                    raise GitHubRateLimitError(
                        "GitHub API rate limit exceeded.",
                        reset_time=_rate_limit_reset(response),
                        status_code=response.status_code,
                    )

                # Check for Not Found
                if response.status_code == 404:
                    raise GitHubNotFoundError(f"Resource not found: {url}")

                # GitHub answers 409 Conflict for the commit list of an empty repository
                if response.status_code == 409:
                    raise GitHubEmptyRepositoryError(f"Repository is empty: {url}")

                response.raise_for_status()

                # Handle 204 No Content (e.g. empty repository logs)
                if response.status_code == 204:
                    return None

                return response.text if raw else response.json()

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                # Retry on transient server errors
                if status_code in [500, 502, 503, 504] and attempt < max_retries - 1:
                    sleep_time = backoff_factor**attempt
                    logger.warning(
                        f"Transient error {status_code}. Retrying in {sleep_time:.2f}s..."
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                raise GitHubAPIError(
                    f"HTTP error {status_code}: {e.response.text[:200]}", status_code=status_code
                ) from e

            except httpx.RequestError as e:
                # Retry on connection/timeout issues
                if attempt < max_retries - 1:
                    sleep_time = backoff_factor**attempt
                    logger.warning(f"Connection error: {str(e)}. Retrying in {sleep_time:.2f}s...")
                    await asyncio.sleep(sleep_time)
                    continue
                raise GitHubAPIError(f"Network error connecting to GitHub: {str(e)}") from e

    async def fetch_repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """
        Fetches core repository metadata.
        Endpoint: GET /repos/{owner}/{repo}
        """
        return await self._make_request("GET", f"/repos/{owner}/{repo}")

    async def fetch_languages(self, owner: str, repo: str) -> dict[str, int]:
        """
        Fetches language breakdown for the repository in bytes.
        Endpoint: GET /repos/{owner}/{repo}/languages
        """
        return await self._make_request("GET", f"/repos/{owner}/{repo}/languages") or {}

    async def fetch_contributors(
        self, owner: str, repo: str, per_page: int = 100
    ) -> list[dict[str, Any]]:
        """
        Fetches the list of contributors for a repository.
        Endpoint: GET /repos/{owner}/{repo}/contributors
        """
        try:
            return (
                await self._make_request(
                    "GET",
                    f"/repos/{owner}/{repo}/contributors",
                    params={"per_page": per_page},
                )
                or []
            )
        except GitHubNotFoundError:
            # Empty repositories can return 404 for contributors endpoint
            return []

    async def fetch_contents(self, owner: str, repo: str, path: str = "") -> list[dict[str, Any]]:
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

    async def fetch_recent_commits(
        self, owner: str, repo: str, since_iso: str
    ) -> list[dict[str, Any]]:
        """
        Fetches the commits for a repository since a specific ISO 8601 date.
        Endpoint: GET /repos/{owner}/{repo}/commits
        """
        try:
            return (
                await self._make_request(
                    "GET",
                    f"/repos/{owner}/{repo}/commits",
                    params={"since": since_iso, "per_page": 100},
                )
                or []
            )
        except GitHubNotFoundError:
            return []

    async def fetch_file_text(self, owner: str, repo: str, path: str) -> str | None:
        """
        Fetches one file's text, or None when it does not exist.
        Endpoint: GET /repos/{owner}/{repo}/contents/{path} with the raw media type,
        which returns the file itself (no base64, and files above 1 MB work too).
        """
        try:
            return await self._make_request(
                "GET", f"/repos/{owner}/{repo}/contents/{path}", raw=True
            )
        except GitHubNotFoundError:
            return None
