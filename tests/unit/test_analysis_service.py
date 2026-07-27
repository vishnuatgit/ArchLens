import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.analysis_service import AnalysisService

@pytest.fixture
def analysis_service():
    return AnalysisService()

@pytest.mark.asyncio
async def test_analysis_run(analysis_service):
    with patch("app.services.github_service.GitHubService.fetch_repo_metadata", new_callable=AsyncMock) as mock_meta, \
         patch("app.services.github_service.GitHubService.fetch_languages", new_callable=AsyncMock) as mock_langs, \
         patch("app.services.github_service.GitHubService.fetch_contents", new_callable=AsyncMock) as mock_dir, \
         patch("app.services.github_service.GitHubService.fetch_recent_commits", new_callable=AsyncMock) as mock_commits, \
         patch("app.services.repository_service.RepositoryService.get_or_create_repository") as mock_get_repo, \
         patch("app.services.repository_service.RepositoryService.save_analysis") as mock_save:
        
        mock_meta.return_value = {"stargazers_count": 100, "updated_at": "2023-01-01T00:00:00Z", "size": 1000, "has_wiki": True}
        mock_langs.return_value = {"Python": 1000}
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
