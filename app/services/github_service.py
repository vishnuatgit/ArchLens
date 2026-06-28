import re
import logging
from typing import Tuple, Optional, Dict, Any
import httpx
from app.config import settings

logger = logging.getLogger("ArchLens.github_service")

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
    # Regex to capture the owner and repository name
    pattern = r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/\s\?#]+)(?:\.git)?(?:/|$)"
    match = re.search(pattern, url, re.IGNORECASE)
    if match:
        owner, repo = match.group(1), match.group(2)
        # Ensure they are not empty strings or basic paths
        if owner and repo:
            return owner, repo
            
    return None, None

class GitHubService:
    """
    Service client to communicate asynchronously with the GitHub REST API.
    Handles authentication and parses responses.
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

    async def fetch_repo_metadata(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Fetches core repository metadata.
        Endpoint: GET /repos/{owner}/{repo}
        """
        url = f"{self.base_url}/repos/{owner}/{repo}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=10.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"GitHub API error fetching metadata for {owner}/{repo}: {e.response.status_code} - {e.response.text}")
                raise e
            except Exception as e:
                logger.error(f"Network error fetching metadata for {owner}/{repo}: {str(e)}")
                raise e

    async def fetch_languages(self, owner: str, repo: str) -> Dict[str, int]:
        """
        Fetches language breakdown for the repository in bytes.
        Endpoint: GET /repos/{owner}/{repo}/languages
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/languages"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=10.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"GitHub API error fetching languages for {owner}/{repo}: {e.response.status_code}")
                raise e
            except Exception as e:
                logger.error(f"Network error fetching languages for {owner}/{repo}: {str(e)}")
                raise e
