import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application settings for ArchLens.
    Loads variables from environment or a local .env file.
    """
    DATABASE_URL: str = "sqlite:///./ArchLens.db"
    GITHUB_TOKEN: Optional[str] = None
    LOG_LEVEL: str = "INFO"

    # Configure Pydantic to read from .env file if it exists
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings to be imported across the application
settings = Settings()
