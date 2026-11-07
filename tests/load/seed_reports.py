"""
Fills a database with stored reports for the load test, without calling GitHub.

    DATABASE_URL=sqlite:///./load.db alembic upgrade head
    DATABASE_URL=sqlite:///./load.db python tests/load/seed_reports.py

It copies the bundled example reports (app/seed/examples.json) under many repository names,
with varied scores and dates, and gives every third one a dependency scan with vulnerabilities,
so the pages the load test visits look like a database that has been in use for a while.
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.db_models import Analysis, Metric, Repository  # noqa: E402
from app.repositories.db import SessionLocal  # noqa: E402
from app.services.dependency_service import (  # noqa: E402
    Dependency,
    DependencyScan,
    Vulnerability,
)
from app.services.metrics_service import grade_for_score  # noqa: E402
from app.services.seed_service import load_examples  # noqa: E402

REPOSITORIES = 60
REPORTS_PER_REPOSITORY = 3


def sample_scan() -> DependencyScan:
    dependencies = [
        Dependency(f"package-{i}", "PyPI", f"=={i}.0.0", f"{i}.0.0", "requirements.txt")
        for i in range(1, 13)
    ]
    dependencies.append(Dependency("loose", "PyPI", ">=1", None, "requirements.txt"))
    vulnerabilities = [
        Vulnerability(
            f"GHSA-load-test-{i:04d}", "package-1", "PyPI", "1.0.0", "high", "Example", "9.9.9"
        )
        for i in range(3)
    ]
    return DependencyScan(
        status="ok",
        manifests=["requirements.txt"],
        dependencies=dependencies,
        vulnerability_check="ok",
        vulnerabilities=vulnerabilities,
        checked=12,
    )


def main() -> None:
    random.seed(7)  # the same data every time, so runs are comparable
    examples = load_examples()
    scan_json = json.dumps(sample_scan().to_dict())
    db = SessionLocal()
    try:
        for r in range(REPOSITORIES):
            template = examples[r % len(examples)]
            repo = Repository(
                owner=f"loadtest{r % 12}",
                name=f"project-{r}",
                url=f"https://github.com/loadtest{r % 12}/project-{r}",
            )
            db.add(repo)
            db.flush()
            for k in range(REPORTS_PER_REPOSITORY):
                score = random.randint(25, 98)
                created = datetime(2026, 10, 1) + timedelta(days=k * 7, hours=r)
                analysis = Analysis(
                    repository_id=repo.id,
                    score=score,
                    duration=template["duration"],
                    repo_type=template["repo_type"],
                    created_at=created,
                )
                db.add(analysis)
                db.flush()
                m = template["metrics"]
                db.add(
                    Metric(
                        analysis_id=analysis.id,
                        stars=m["stars"],
                        forks=m["forks"],
                        open_issues=m["open_issues"],
                        language_count=m["language_count"],
                        contributor_count=m["contributor_count"],
                        repo_size=m["repo_size"],
                        security_score=m["security_score"],
                        code_quality_score=m["code_quality_score"],
                        health_grade=grade_for_score(score),
                        executive_summary=m["executive_summary"],
                        languages_json=json.dumps(m["languages"]),
                        score_breakdown_json=json.dumps(m["score_breakdown"]),
                        strengths_json=json.dumps(m["strengths"]),
                        weaknesses_json=json.dumps(m["weaknesses"]),
                        suggestions_json=json.dumps(m["suggestions"]),
                        dependencies_json=scan_json if (r + k) % 3 == 0 else None,
                    )
                )
        db.commit()
        print(f"Seeded {REPOSITORIES} repositories with {REPORTS_PER_REPOSITORY} reports each")
    finally:
        db.close()


if __name__ == "__main__":
    main()
