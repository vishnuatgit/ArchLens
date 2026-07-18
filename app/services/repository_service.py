import json
import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.db_models import Repository, Analysis, Metric

logger = logging.getLogger("ArchLens.repository_service")


class RepositoryService:
    """
    Handles all database persistence operations for repositories, analyses, and metrics.
    """

    def get_or_create_repository(
        self, db: Session, owner: str, name: str, url: str
    ) -> Repository:
        """
        Returns an existing repository record or creates a new one if not found.
        """
        repo = db.query(Repository).filter(Repository.url == url).first()
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
    ) -> Analysis:
        """
        Persists a full analysis run including score breakdown, metrics, and recommendations.
        """
        last_pushed = None
        pushed_at_str = metadata.get("pushed_at")
        if pushed_at_str:
            try:
                last_pushed = datetime.fromisoformat(
                    pushed_at_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"Failed to parse pushed_at timestamp: {str(e)}")

        # Compute language percentages from raw byte counts
        total_bytes = sum(languages.values()) or 1
        language_percentages = {
            lang: round((count / total_bytes) * 100, 1)
            for lang, count in languages.items()
        }

        analysis = Analysis(repository_id=repository_id, score=score, duration=duration)
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

    def get_analysis_by_id(self, db: Session, analysis_id: int) -> Optional[Analysis]:
        """
        Retrieves a single analysis record by primary key, including related metrics.
        """
        return db.query(Analysis).filter(Analysis.id == analysis_id).first()

    def get_history(
        self, db: Session, limit: int = 20, offset: int = 0
    ) -> List[Analysis]:
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
