from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class RepositoryBase(BaseModel):
    url: str

class RepositoryCreate(RepositoryBase):
    owner: str
    name: str

class RepositoryResponse(BaseModel):
    id: int
    owner: str
    name: str
    url: str
    created_at: datetime

    class Config:
        from_attributes = True

class MetricResponse(BaseModel):
    id: int
    analysis_id: int
    stars: int
    forks: int
    open_issues: int
    language_count: int
    contributor_count: int
    repo_size: int
    last_pushed: Optional[datetime] = None
    
    # Complex fields parsed from database JSON strings
    languages: Dict[str, int] = Field(default_factory=dict)
    score_breakdown: Dict[str, int] = Field(default_factory=dict)
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True

class AnalysisResponse(BaseModel):
    id: int
    repository_id: int
    score: int
    duration: float
    created_at: datetime
    metrics: Optional[MetricResponse] = None

    class Config:
        from_attributes = True

class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="GitHub repository URL (e.g. https://github.com/owner/repo)")

class AnalyzeResponse(BaseModel):
    analysis_id: int
    status: str = "completed"
