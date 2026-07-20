from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.repositories.db import Base


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Repository(Base):
    """
    SQLAlchemy model representing a GitHub repository submitted for analysis.
    """

    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    owner = Column(String, nullable=False)
    name = Column(String, nullable=False)
    url = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)

    # Establish one-to-many relationship with analysis records
    analyses = relationship(
        "Analysis", back_populates="repository", cascade="all, delete-orphan"
    )


class Analysis(Base):
    """
    SQLAlchemy model representing a single analysis run for a repository.
    """

    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(
        Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    score = Column(Integer, nullable=False)
    duration = Column(Float, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)

    # Establish relationships
    repository = relationship("Repository", back_populates="analyses")
    metrics = relationship(
        "Metric", uselist=False, back_populates="analysis", cascade="all, delete-orphan"
    )


class Metric(Base):
    """
    SQLAlchemy model representing the parsed raw metrics and calculated scores.
    """

    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(
        Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )

    # Raw GitHub Stats
    stars = Column(Integer, nullable=False, default=0)
    forks = Column(Integer, nullable=False, default=0)
    open_issues = Column(Integer, nullable=False, default=0)
    language_count = Column(Integer, nullable=False, default=0)
    contributor_count = Column(Integer, nullable=False, default=0)
    repo_size = Column(Integer, nullable=False, default=0)  # size in KB
    last_pushed = Column(DateTime, nullable=True)

    # Serialized JSON structures for complex breakdowns and recommendations
    languages_json = Column(Text, nullable=True)  # e.g., {"Python": 80.5, "HTML": 19.5}
    score_breakdown_json = Column(
        Text, nullable=True
    )  # e.g., {"documentation": 15, "activity": 18, ...}
    strengths_json = Column(
        Text, nullable=True
    )  # e.g., ["Has README", "Active last 30 days"]
    weaknesses_json = Column(
        Text, nullable=True
    )  # e.g., ["No LICENSE", "High open issue ratio"]
    suggestions_json = Column(
        Text, nullable=True
    )  # e.g., ["Add a LICENSE file to define usage rules"]

    # Establish relationship
    analysis = relationship("Analysis", back_populates="metrics")
