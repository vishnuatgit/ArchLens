"""
Custom exception hierarchy for ArchLens.

Centralises all application-specific errors so that routers can map
them to appropriate HTTP status codes in a single exception handler.
Each subclass declares the status code and machine-readable error code
returned by the REST API; the web form shows the same message inline.
"""

import math
import time


def _minutes_until(epoch: float | None) -> int | None:
    """Rounds the time left until a Unix timestamp up to whole minutes."""
    if epoch is None:
        return None
    return max(1, math.ceil((epoch - time.time()) / 60))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class ArchLensError(Exception):
    """Base exception for all ArchLens application errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "An unexpected error occurred."):
        self.message = message
        super().__init__(self.message)

    @property
    def retry_after_seconds(self) -> int | None:
        """Seconds a client should wait before retrying, when known."""
        return None


class InvalidRepositoryURLError(ArchLensError):
    """Raised when the submitted URL is not a valid GitHub repository URL."""

    status_code = 400
    error_code = "INVALID_URL"

    def __init__(self, url: str):
        super().__init__(
            f"Invalid or unsupported GitHub repository URL: {url}. "
            "Use owner/repo or https://github.com/owner/repo."
        )
        self.url = url


class InvalidRepoTypeError(ArchLensError):
    """Raised when the requested repository profile is not supported."""

    status_code = 400
    error_code = "INVALID_REPO_TYPE"

    def __init__(self, repo_type: str, allowed: list[str]):
        super().__init__(
            f"Unknown repository profile '{repo_type}'. Choose one of: {', '.join(allowed)}."
        )
        self.repo_type = repo_type


class RepositoryNotFoundError(ArchLensError):
    """Raised when the target repository does not exist on GitHub (404)."""

    status_code = 404
    error_code = "REPO_NOT_FOUND"

    def __init__(self, owner: str, name: str):
        super().__init__(
            f"Repository '{owner}/{name}' was not found on GitHub. "
            "Check the spelling; private repositories can't be analyzed."
        )
        self.owner = owner
        self.name = name


class EmptyRepositoryError(ArchLensError):
    """Raised when the repository exists but has no commits yet (GitHub 409)."""

    status_code = 422
    error_code = "EMPTY_REPOSITORY"

    def __init__(self, owner: str, name: str):
        super().__init__(f"Repository '{owner}/{name}' is empty, so there is nothing to analyze.")
        self.owner = owner
        self.name = name


class RateLimitExceededError(ArchLensError):
    """Raised when the GitHub API rate limit has been exhausted."""

    status_code = 503
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, reset_epoch: int | None = None):
        minutes = _minutes_until(reset_epoch)
        wait = f"in about {_plural(minutes, 'minute')}" if minutes else "later"
        super().__init__(
            "GitHub API rate limit exceeded: this server shares GitHub's anonymous API limit "
            f"with every visitor, and it has run out for now. Please try again {wait}, "
            "or browse the example reports in the meantime."
        )
        self.reset_epoch = reset_epoch

    @property
    def retry_after_seconds(self) -> int | None:
        if self.reset_epoch is None:
            return None
        return max(1, int(self.reset_epoch - time.time()))


class TooManyAnalysesError(ArchLensError):
    """Raised when one client starts too many analyses within the rate-limit window."""

    status_code = 429
    error_code = "TOO_MANY_ANALYSES"

    def __init__(self, limit: int, window_seconds: int, retry_after: float):
        self.retry_after = max(1, math.ceil(retry_after))
        minutes = max(1, math.ceil(self.retry_after / 60))
        analyses = "new analysis" if limit == 1 else "new analyses"
        super().__init__(
            f"This demo allows {limit} {analyses} per {_plural(window_seconds // 60, 'minute')} "
            f"from each visitor. Please wait about {_plural(minutes, 'minute')} "
            "before starting another one."
        )

    @property
    def retry_after_seconds(self) -> int | None:
        return self.retry_after


class UpstreamServiceError(ArchLensError):
    """Raised when GitHub returns an unexpected error or cannot be reached."""

    status_code = 502
    error_code = "GITHUB_UNAVAILABLE"

    def __init__(self, detail: str):
        super().__init__(
            f"GitHub could not complete the request ({detail}). Please try again in a few minutes."
        )
        self.detail = detail


class AnalysisNotFoundError(ArchLensError):
    """Raised when a requested analysis ID does not exist in the database."""

    status_code = 404
    error_code = "ANALYSIS_NOT_FOUND"

    def __init__(self, analysis_id: int):
        super().__init__(f"Analysis with ID {analysis_id} was not found.")
        self.analysis_id = analysis_id


class PersistenceError(ArchLensError):
    """Raised when a database write operation fails."""

    status_code = 500
    error_code = "PERSISTENCE_ERROR"

    def __init__(self, detail: str = "Failed to save data to the database."):
        super().__init__(detail)
