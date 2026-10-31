import json
import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.db_models import Analysis, Metric, Repository, RepositoryAlias

logger = logging.getLogger("ArchLens.repository_service")

# History orderings offered on the history page
HISTORY_SORTS = {
    "newest": (Analysis.created_at.desc(),),
    "oldest": (Analysis.created_at.asc(),),
    "score_high": (Analysis.score.desc(), Analysis.created_at.desc()),
    "score_low": (Analysis.score.asc(), Analysis.created_at.desc()),
    "name": (func.lower(Repository.owner), func.lower(Repository.name)),
}


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

    def resolve_url(self, db: Session, url: str) -> str:
        """
        Follows a recorded rename: returns the current canonical URL of a repository
        that used to live at `url`, or `url` itself when no rename is known.
        """
        alias = (
            db.query(RepositoryAlias).filter(func.lower(RepositoryAlias.url) == url.lower()).first()
        )
        return alias.repository.url if alias else url

    def record_rename(self, db: Session, repository: Repository, requested_url: str) -> None:
        """
        Remembers that `requested_url` now leads to `repository` (GitHub followed a rename
        or transfer). The repository's own URL is never kept as an alias, so a name that
        has become a different repository again stops redirecting.
        """
        db.query(RepositoryAlias).filter(
            func.lower(RepositoryAlias.url) == repository.url.lower()
        ).delete(synchronize_session=False)
        if requested_url.lower() != repository.url.lower():
            alias = (
                db.query(RepositoryAlias)
                .filter(func.lower(RepositoryAlias.url) == requested_url.lower())
                .first()
            )
            if alias:
                alias.repository_id = repository.id
            else:
                db.add(RepositoryAlias(repository_id=repository.id, url=requested_url))
            logger.info(f"Recorded rename: {requested_url} -> {repository.url}")
        db.commit()

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
        created at or after `since`, so a repeat request can reuse it. An old name of a
        renamed repository finds the reports stored under its new name.
        """
        url = self.resolve_url(db, url)
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

    def get_latest_analysis(
        self, db: Session, url: str, repo_type: str | None = None
    ) -> Analysis | None:
        """
        Returns the newest stored analysis of a repository (any age, examples included),
        optionally for one profile. The badge, compare page and /repo links use this
        so they can answer from stored results without calling GitHub. Old names of
        renamed repositories are followed.
        """
        url = self.resolve_url(db, url)
        query = (
            db.query(Analysis).join(Repository).filter(func.lower(Repository.url) == url.lower())
        )
        if repo_type:
            query = query.filter(Analysis.repo_type == repo_type)
        return query.order_by(Analysis.created_at.desc(), Analysis.id.desc()).first()

    def get_example_analyses(self, db: Session) -> list[Analysis]:
        """Returns the bundled example reports in the order they were loaded."""
        return db.query(Analysis).filter(Analysis.is_example.is_(True)).order_by(Analysis.id).all()

    def list_repository_names(self, db: Session, limit: int = 50) -> list[str]:
        """Returns 'owner/name' of stored repositories, newest first (form suggestions)."""
        repos = db.query(Repository).order_by(Repository.created_at.desc()).limit(limit).all()
        return [f"{repo.owner}/{repo.name}" for repo in repos]

    def list_stored_reports(self, db: Session) -> list[str]:
        """
        Every stored repository and profile pair as "owner/name:profile", lowercased.
        The compare page uses it to say whether a comparison needs GitHub at all.
        """
        rows = (
            db.query(Repository.owner, Repository.name, Analysis.repo_type)
            .join(Analysis)
            .distinct()
            .all()
        )
        return sorted(f"{owner}/{name}:{profile}".lower() for owner, name, profile in rows)

    def get_featured_analysis(self, db: Session) -> Analysis | None:
        """
        Returns the analysis previewed on the home page: the first example report,
        or the most recent analysis when no examples are loaded.
        """
        examples = self.get_example_analyses(db)
        if examples:
            return examples[0]
        return db.query(Analysis).order_by(Analysis.created_at.desc()).first()

    def _history_query(self, db: Session, search: str | None, repo_type: str | None):
        query = db.query(Analysis).join(Repository)
        if search:
            # Matches anywhere in "owner/name", so "psf/req" and "requests" both work
            full_name = func.lower(Repository.owner + "/" + Repository.name)
            query = query.filter(full_name.contains(search.strip().lower(), autoescape=True))
        if repo_type:
            query = query.filter(Analysis.repo_type == repo_type)
        return query

    def get_history(
        self,
        db: Session,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        repo_type: str | None = None,
        sort: str = "newest",
    ) -> list[Analysis]:
        """
        Returns a page of analyses, newest first unless `sort` names another HISTORY_SORTS
        order, optionally filtered by repository name and profile.
        """
        order = HISTORY_SORTS.get(sort, HISTORY_SORTS["newest"])
        return (
            self._history_query(db, search, repo_type)
            .order_by(*order, Analysis.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_history(
        self, db: Session, search: str | None = None, repo_type: str | None = None
    ) -> int:
        """Counts what get_history pages through with the same filters."""
        return self._history_query(db, search, repo_type).count()

    def get_repository_timeline(self, db: Session, repository_id: int) -> list[Analysis]:
        """Every stored analysis of one repository, oldest first (the report's score history)."""
        return (
            db.query(Analysis)
            .filter(Analysis.repository_id == repository_id)
            .order_by(Analysis.created_at, Analysis.id)
            .all()
        )
