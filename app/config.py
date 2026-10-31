from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings for ArchLens.
    Loads variables from environment or a local .env file.
    """

    DATABASE_URL: str = "sqlite:///./ArchLens.db"
    GITHUB_TOKEN: str | None = None
    LOG_LEVEL: str = "INFO"

    # Public demo protection: reuse recent reports instead of calling GitHub again,
    # and cap how many new analyses one client can start per window (0 disables each)
    ANALYSIS_CACHE_MINUTES: int = 60
    ANALYSIS_RATE_LIMIT: int = 5
    ANALYSIS_RATE_WINDOW_SECONDS: int = 600

    # Load the bundled example reports on startup when the database is empty
    SEED_EXAMPLES: bool = True

    # Configure Pydantic to read from .env file if it exists
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


# Instantiate settings to be imported across the application
settings = Settings()

# Project links shown in the footer, the About page and exported reports
SITE = {
    "author": "Vishnu Jayanth",
    "portfolio_url": "https://vishnuatgit.github.io",
    "repo_url": "https://github.com/vishnuatgit/ArchLens",
}
