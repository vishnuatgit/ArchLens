"""
Custom exception hierarchy for ArchLens.

Centralises all application-specific errors so that routers can map
them to appropriate HTTP status codes in a single exception handler.
"""


class ArchLensError(Exception):
    """Base exception for all ArchLens application errors."""

    def __init__(self, message: str = "An unexpected error occurred."):
        self.message = message
        super().__init__(self.message)


class InvalidRepositoryURLError(ArchLensError):
    """Raised when the submitted URL is not a valid GitHub repository URL."""

    def __init__(self, url: str):
        super().__init__(f"Invalid or unsupported GitHub repository URL: {url}")
        self.url = url


class RepositoryNotFoundError(ArchLensError):
    """Raised when the target repository does not exist on GitHub (404)."""

    def __init__(self, owner: str, name: str):
        super().__init__(f"Repository '{owner}/{name}' was not found on GitHub.")
        self.owner = owner
        self.name = name


class RateLimitExceededError(ArchLensError):
    """Raised when the GitHub API rate limit has been exhausted."""

    def __init__(self, reset_epoch: int | None = None):
        super().__init__("GitHub API rate limit exceeded. Try again later.")
        self.reset_epoch = reset_epoch


class AnalysisNotFoundError(ArchLensError):
    """Raised when a requested analysis ID does not exist in the database."""

    def __init__(self, analysis_id: int):
        super().__init__(f"Analysis with ID {analysis_id} was not found.")
        self.analysis_id = analysis_id


class PersistenceError(ArchLensError):
    """Raised when a database write operation fails."""

    def __init__(self, detail: str = "Failed to save data to the database."):
        super().__init__(detail)
