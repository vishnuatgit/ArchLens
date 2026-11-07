from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.metrics_service import RepoType


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
    last_pushed: datetime | None = None

    security_score: int = 0
    code_quality_score: int = 0
    health_grade: str = "C"
    executive_summary: str = ""

    # Deserialized breakdown fields
    languages: dict[str, float] = Field(default_factory=dict)
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DependencyResponse(BaseModel):
    """One direct dependency read from a manifest."""

    name: str
    ecosystem: str = Field(description="PyPI, npm or Go")
    spec: str = Field(description="The version constraint as written in the manifest")
    version: str | None = Field(description="The exact version, or null when it is not pinned")
    pinned: bool
    source: str = Field(description="The manifest the dependency came from")
    dev: bool = False


class VulnerabilityResponse(BaseModel):
    """A known advisory for a pinned dependency (from OSV.dev)."""

    id: str
    url: str
    package: str
    ecosystem: str
    version: str
    severity: str = Field(description="critical, high, medium, low or unknown")
    summary: str = ""
    fixed: str | None = Field(None, description="Upgrade to this version or later, when known")
    aliases: list[str] = Field(default_factory=list)


class DependencyScanResponse(BaseModel):
    """
    Dependencies and known vulnerabilities. Informational: they do not change the score.
    `status` is ok, none (no supported manifest in the repository root) or error.
    `vulnerability_check` is ok, unavailable (OSV could not be reached) or skipped.
    """

    status: str
    manifests: list[str] = Field(default_factory=list)
    dependencies: list[DependencyResponse] = Field(default_factory=list)
    vulnerability_check: str
    vulnerabilities: list[VulnerabilityResponse] = Field(default_factory=list)
    checked: int = 0
    notes: list[str] = Field(default_factory=list)


class AnalysisDetailResponse(BaseModel):
    """Complete analysis response schema."""

    id: int
    score: int
    health_grade: str = "C"
    executive_summary: str = ""
    duration: float
    repo_type: str
    is_example: bool = False
    created_at: datetime
    repository: RepositoryResponse
    metrics: MetricApiResponse | None = None
    dependency_scan: DependencyScanResponse | None = Field(
        None, description="null for reports stored before dependency scanning existed"
    )

    model_config = ConfigDict(from_attributes=True)


class AnalysisSummaryResponse(BaseModel):
    """Lightweight analysis summary for paginated lists."""

    id: int
    score: int
    health_grade: str = "C"
    duration: float
    repo_type: str
    is_example: bool = False
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
    items: list[AnalysisSummaryResponse]


class AnalyzeApiRequest(BaseModel):
    """Request payload for repository analysis endpoint."""

    url: str = Field(
        ...,
        description="Public GitHub repository URL or owner/repo (e.g. https://github.com/fastapi/fastapi)",
        examples=["https://github.com/fastapi/fastapi"],
    )
    repo_type: RepoType = Field(
        default=RepoType.LIBRARY,
        description="Repository evaluation profile: 'library', 'personal', or 'enterprise'",
        examples=["library"],
    )


class ErrorResponse(BaseModel):
    """Structured API error response schema."""

    error: str = Field(..., description="Human-readable error message")
    error_code: str = Field(..., description="Machine-readable error identifier")
    status_code: int = Field(..., description="HTTP status code")
