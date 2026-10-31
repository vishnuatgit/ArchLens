import json
import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.db_models import Analysis, Metric, Repository

logger = logging.getLogger("ArchLens.repository_service")


class RepositoryService:
    """
    Handles all database persistence operations for repositories, analyses, and metrics.
    """

    def get_or_create_repository(self, db: Session, owner: str, name: str, url: str) -> Repository:
        """
        Returns an existing repository record or creates a new one if not found.
        URLs are matched case-insensitively because GitHub treats owner/repo that way.
        """
        repo = db.query(Repository).filter(func.lower(Repository.url) == url.lower()).first()
        if not repo:
            repo = Repository(owner=owner, name=name, url=url)
            db.add(repo)
            db.commit()
            db.refresh(repo)
            logger.info(f"Created new repository record: {owner}/{name}")
        return repo

    def save_analysis(
        self,
        db: Session,
        repository_id: int,
        score: int,
        duration: float,
        metadata: dict,
        languages: dict,
        contributor_count: int,
        recent_commits: list,
        report: dict,
        repo_type: str = "library",
    ) -> Analysis:
        """
        Persists a full analysis run including score breakdown, metrics, and recommendations.
        """
        last_pushed = None
        pushed_at_str = metadata.get("pushed_at")
        if pushed_at_str:
            try:
                last_pushed = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except Exception as e:
                logger.warning(f"Failed to parse pushed_at timestamp: {str(e)}")

        # Compute language percentages from raw byte counts
        total_bytes = sum(languages.values()) or 1
        language_percentages = {
            lang: round((count / total_bytes) * 100, 1) for lang, count in languages.items()
        }

        analysis = Analysis(
            repository_id=repository_id,
            score=score,
            duration=duration,
            repo_type=repo_type,
        )
        db.add(analysis)
        db.flush()  # Populate analysis.id without committing

        metric = Metric(
            analysis_id=analysis.id,
            stars=metadata.get("stargazers_count", 0) or 0,
            forks=metadata.get("forks_count", 0) or 0,
            open_issues=metadata.get("open_issues_count", 0) or 0,
            language_count=len(languages),
            contributor_count=contributor_count,
            repo_size=metadata.get("size", 0) or 0,
            last_pushed=last_pushed,
            security_score=report.get("security_score", 0),
            code_quality_score=report.get("code_quality_score", 0),
            health_grade=report.get("health_grade", "C"),
            executive_summary=report.get("executive_summary", ""),
            languages_json=json.dumps(language_percentages),
            score_breakdown_json=json.dumps(report.get("breakdown", {})),
            strengths_json=json.dumps(report.get("strengths", [])),
            weaknesses_json=json.dumps(report.get("weaknesses", [])),
            suggestions_json=json.dumps(report.get("suggestions", [])),
        )
        db.add(metric)
        db.commit()
        db.refresh(analysis)
        logger.info(
            f"Saved analysis id={analysis.id} for repository_id={repository_id} with score={score}"
        )
        return analysis

    def get_analysis_by_id(self, db: Session, analysis_id: int) -> Analysis | None:
        """
        Retrieves a single analysis record by primary key, including related metrics.
        """
        return db.query(Analysis).filter(Analysis.id == analysis_id).first()

    def find_recent_analysis(
        self, db: Session, url: str, repo_type: str, since: datetime
    ) -> Analysis | None:
        """
        Returns the newest live (non-example) analysis of a repository and profile
        created at or after `since`, so a repeat request can reuse it.
        """
        return (
            db.query(Analysis)
            .join(Repository)
            .filter(
                func.lower(Repository.url) == url.lower(),
                Analysis.repo_type == repo_type,
                Analysis.is_example.is_(False),
                Analysis.created_at >= since,
            )
            .order_by(Analysis.created_at.desc())
            .first()
        )

    def get_featured_analysis(self, db: Session) -> Analysis | None:
        """
        Returns the analysis previewed on the home page: the first example report,
        or the most recent analysis when no examples are loaded.
        """
        example = (
            db.query(Analysis).filter(Analysis.is_example.is_(True)).order_by(Analysis.id).first()
        )
        return example or db.query(Analysis).order_by(Analysis.created_at.desc()).first()

    def get_history(self, db: Session, limit: int = 20, offset: int = 0) -> list[Analysis]:
        """
        Returns a paginated list of analyses ordered by most recently created.
        """
        return (
            db.query(Analysis)
            .order_by(Analysis.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
