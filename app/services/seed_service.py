"""
Example reports bundled with the application.

The live demo runs on a host whose disk is wiped whenever the service restarts,
so a fresh database would greet visitors with empty pages. On startup, when the
database holds no analyses, the reports in app/seed/examples.json are loaded.
They are real analyses captured by scripts/build_examples.py and keep their
original analysis dates; the UI labels them as examples.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.db_models import Analysis, Metric
from app.services.repository_service import RepositoryService

logger = logging.getLogger("ArchLens.seed_service")

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "seed" / "examples.json"

# Metric columns copied verbatim between the database and the fixture
_METRIC_FIELDS = (
    "stars",
    "forks",
    "open_issues",
    "language_count",
    "contributor_count",
    "repo_size",
    "security_score",
    "code_quality_score",
    "health_grade",
    "executive_summary",
)

# Fixture key -> JSON-encoded Metric column
_METRIC_JSON_FIELDS = {
    "languages": "languages_json",
    "score_breakdown": "score_breakdown_json",
    "strengths": "strengths_json",
    "weaknesses": "weaknesses_json",
    "suggestions": "suggestions_json",
}


def export_example(analysis: Analysis) -> dict[str, Any]:
    """Serialises a stored analysis into the fixture format."""
    m = analysis.metrics
    metrics = {field: getattr(m, field) for field in _METRIC_FIELDS}
    metrics["last_pushed"] = m.last_pushed.isoformat() if m.last_pushed else None
    for key, column in _METRIC_JSON_FIELDS.items():
        metrics[key] = json.loads(getattr(m, column) or "null")

    return {
        "owner": analysis.repository.owner,
        "name": analysis.repository.name,
        "url": analysis.repository.url,
        "repo_type": analysis.repo_type,
        "score": analysis.score,
        "duration": analysis.duration,
        "analyzed_at": analysis.created_at.isoformat(timespec="seconds"),
        "metrics": metrics,
    }


def load_examples(path: Path = EXAMPLES_PATH) -> list[dict[str, Any]]:
    """Reads the example reports from the fixture file."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)["examples"]


def seed_examples_if_empty(db: Session, path: Path = EXAMPLES_PATH) -> int:
    """
    Inserts the example reports when the database has no analyses.
    Returns the number of reports inserted.
    """
    if db.query(Analysis).count() > 0:
        return 0

    examples = load_examples(path)
    repository_service = RepositoryService()
    for example in examples:
        analyzed_at = datetime.fromisoformat(example["analyzed_at"])
        repo = repository_service.get_or_create_repository(
            db, owner=example["owner"], name=example["name"], url=example["url"]
        )
        analysis = Analysis(
            repository_id=repo.id,
            score=example["score"],
            duration=example["duration"],
            repo_type=example["repo_type"],
            is_example=True,
            created_at=analyzed_at,
        )
        db.add(analysis)
        db.flush()

        m = example["metrics"]
        metric = Metric(
            analysis_id=analysis.id,
            last_pushed=datetime.fromisoformat(m["last_pushed"]) if m.get("last_pushed") else None,
            **{field: m[field] for field in _METRIC_FIELDS},
            **{column: json.dumps(m[key]) for key, column in _METRIC_JSON_FIELDS.items()},
        )
        db.add(metric)

    db.commit()
    return len(examples)


def seed_examples_on_startup(session_factory: Callable[[], Session]) -> None:
    """Loads the example reports at startup without ever preventing the app from booting."""
    db = session_factory()
    try:
        inserted = seed_examples_if_empty(db)
        if inserted:
            logger.info(f"Loaded {inserted} example reports into the empty database")
    except (SQLAlchemyError, OSError, KeyError, ValueError) as e:
        db.rollback()
        logger.warning(
            f"Skipped loading example reports ({e.__class__.__name__}: {e}). "
            "Run `alembic upgrade head` if the tables are missing."
        )
    finally:
        db.close()
