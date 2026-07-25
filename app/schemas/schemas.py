from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class RepositoryResponse(BaseModel):
    """Schema for repository details."""

    id: int
    owner: str
    name: str
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricApiResponse(BaseModel):
    """Detailed metric payload including 7-dimension breakdown, summary, and grade."""

    id: int
    analysis_id: int
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    language_count: int = 0
    contributor_count: int = 0
    repo_size: int = 0  # size in KB
    last_pushed: Optional[datetime] = None

    security_score: int = 0
    code_quality_score: int = 0
    health_grade: str = "C"
    executive_summary: str = ""

    # Deserialized breakdown fields
    languages: Dict[str, float] = Field(default_factory=dict)
    score_breakdown: Dict[str, int] = Field(default_factory=dict)
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AnalysisDetailResponse(BaseModel):
    """Complete analysis response schema."""

    id: int
    score: int
    health_grade: str = "C"
    executive_summary: str = ""
    duration: float
    repo_type: str
    created_at: datetime
    repository: RepositoryResponse
    metrics: Optional[MetricApiResponse] = None

    model_config = ConfigDict(from_attributes=True)


class AnalysisSummaryResponse(BaseModel):
    """Lightweight analysis summary for paginated lists."""

    id: int
    score: int
    health_grade: str = "C"
    duration: float
    repo_type: str
    created_at: datetime
    repo_owner: str
    repo_name: str
    repo_url: str

    model_config = ConfigDict(from_attributes=True)


class PaginatedAnalysisResponse(BaseModel):
    """Paginated list response wrapper."""

    total: int
    offset: int
    limit: int
    items: List[AnalysisSummaryResponse]


class AnalyzeApiRequest(BaseModel):
    """Request payload for repository analysis endpoint."""

    url: str = Field(
        ...,
        description="Public GitHub repository URL (e.g. https://github.com/fastapi/fastapi)",
        examples=["https://github.com/fastapi/fastapi"],
    )
    repo_type: str = Field(
        default="library",
        description="Repository evaluation profile: 'library', 'personal', or 'enterprise'",
        examples=["library"],
    )


class ErrorResponse(BaseModel):
    """Structured API error response schema."""

    error: str = Field(..., description="Human-readable error message")
    error_code: str = Field(..., description="Machine-readable error identifier")
    status_code: int = Field(..., description="HTTP status code")

