"""
Integration tests for the streamed analysis progress, the history filters,
and what the report and compare pages show beyond the scores.

GitHub is never contacted: the analysis service is a mock, or a real
AnalysisService whose GitHub client is stubbed.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.dependencies import get_analysis_service
from app.exceptions import TooManyAnalysesError
from app.models import db_models  # noqa: F401
from app.models.db_models import Analysis, Metric, Repository
from app.repositories.db import Base, get_db
from app.routers.web import HISTORY_SORT_LABELS
from app.services.analysis_service import AnalysisService
from app.services.repository_service import HISTORY_SORTS
from main import app
from tests.integration.conftest import override_get_db, test_engine

app.dependency_overrides[get_db] = override_get_db
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# A psf/requests report as the real scorer stores it
REQUESTS = {
    "breakdown": {
        "documentation": 15,
        "activity": 9,
        "organization": 15,
        "community": 15,
        "maintainability": 11,
        "security": 3,
        "code_quality": 9,
    },
    "strengths": [
        "Found repository README.",
        "Found LICENSE permissions file.",
        "Found documentation/contributing guidelines.",
        "Low commit activity: 1 commit(s) in the last 30 days.",
        "Repository updated recently (within the last 30 days).",
        "Found dedicated test suite directory.",
        "Source code organized into a dedicated subdirectory.",
        "Found workspace configuration files.",
        "Strong community interest with 54,641 stars.",
        "High fork count (12,089).",
        "Active contributor base with 100+ contributors.",
        "Found 8 GitHub Actions workflow(s).",
        "Repository size is lean and well-managed.",
        "Found .gitignore secret protection file.",
        "Found linter/formatter configuration (Ruff/ESLint/Prettier/pyproject.toml).",
        "Found .pre-commit-config.yaml git hooks automation.",
    ],
    "weaknesses": [
        "High open issue count (245).",
        "Missing dependency lockfile (e.g. requirements.txt, package-lock.json).",
        "Missing SECURITY.md vulnerability reporting policy.",
        "Missing explicit static type checker configuration.",
    ],
    "suggestions": [
        "Commit a dependency lockfile for reproducible deployments.",
        "Add a SECURITY.md file detailing security issue reporting.",
        "Add static type checking configuration (e.g. mypy.ini or tsconfig.json).",
    ],
}


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    app.dependency_overrides.pop(get_analysis_service, None)


@pytest.fixture()
def client():
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def add_analysis(
    db,
    owner="psf",
    name="requests",
    score=77,
    repo_type="library",
    is_example=False,
    created_at=datetime(2026, 10, 31, 12, 0, 0),
):
    url = f"https://github.com/{owner}/{name}"
    repo = db.query(Repository).filter(Repository.url == url).first()
    if repo is None:
        repo = Repository(owner=owner, name=name, url=url)
        db.add(repo)
        db.flush()
    analysis = Analysis(
        repository_id=repo.id,
        score=score,
        duration=1.2,
        repo_type=repo_type,
        is_example=is_example,
        created_at=created_at,
    )
    db.add(analysis)
    db.flush()
    db.add(
        Metric(
            analysis_id=analysis.id,
            stars=54641,
            forks=12089,
            open_issues=245,
            contributor_count=100,
            repo_size=13635,
            language_count=2,
            last_pushed=created_at - timedelta(days=5),
            health_grade="B+",
            executive_summary="Summary.",
            languages_json=json.dumps({"Python": 99.4, "Makefile": 0.6}),
            score_breakdown_json=json.dumps(REQUESTS["breakdown"]),
            strengths_json=json.dumps(REQUESTS["strengths"]),
            weaknesses_json=json.dumps(REQUESTS["weaknesses"]),
            suggestions_json=json.dumps(REQUESTS["suggestions"]),
        )
    )
    db.commit()
    db.refresh(analysis)
    return analysis


def read_events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def use_service(service) -> None:
    app.dependency_overrides[get_analysis_service] = lambda: service


# ---------------------------------------------------------------------------
# POST /api/v1/analyze/stream
# ---------------------------------------------------------------------------


class TestProgressStream:
    def test_streams_progress_then_the_report_address(self, client):
        async def run(**kwargs):
            kwargs["progress"]({"event": "progress", "step": "validate", "status": "done"})
            kwargs["progress"]({"event": "progress", "step": "save", "status": "done"})
            return {"analysis_id": 12, "score": 77, "reused": False}

        service = AsyncMock(spec=AnalysisService)
        service.run = AsyncMock(side_effect=run)
        use_service(service)

        response = client.post(
            "/api/v1/analyze/stream",
            json={"url": "psf/requests", "repo_type": "personal"},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert response.headers["cache-control"] == "no-store"
        events = read_events(response)
        assert [e["event"] for e in events] == ["progress", "progress", "done"]
        assert events[-1] == {
            "event": "done",
            "analysis_id": 12,
            "report_url": "/analysis/12",
            "reused": False,
            "score": 77,
        }
        kwargs = service.run.await_args.kwargs
        assert kwargs["repo_type"] == "personal"
        assert kwargs["client_id"] == "203.0.113.5"

    def test_errors_arrive_as_an_event_with_the_usual_code(self, client):
        service = AsyncMock(spec=AnalysisService)
        service.run = AsyncMock(side_effect=TooManyAnalysesError(5, 600, 120))
        use_service(service)

        events = read_events(client.post("/api/v1/analyze/stream", json={"url": "a/b"}))
        assert events == [
            {
                "event": "error",
                "error": events[0]["error"],
                "error_code": "TOO_MANY_ANALYSES",
                "status_code": 429,
                "retry_after": 120,
            }
        ]
        assert "Please wait about 2 minutes" in events[0]["error"]

    def test_unexpected_failures_do_not_leak_details(self, client):
        service = AsyncMock(spec=AnalysisService)
        service.run = AsyncMock(side_effect=RuntimeError("secret internals"))
        use_service(service)

        events = read_events(client.post("/api/v1/analyze/stream", json={"url": "a/b"}))
        assert events[-1]["error_code"] == "INTERNAL_ERROR"
        assert "secret" not in events[-1]["error"]

    def test_invalid_input_is_rejected_before_streaming(self, client):
        service = AsyncMock(spec=AnalysisService)
        use_service(service)

        response = client.post("/api/v1/analyze/stream", json={"url": "not a repo"})
        assert response.status_code == 400
        assert response.json()["error_code"] == "INVALID_URL"
        bad_profile = client.post("/api/v1/analyze/stream", json={"url": "a/b", "repo_type": "x"})
        assert bad_profile.status_code == 422
        service.run.assert_not_awaited()

    def test_real_analysis_reports_each_github_call_and_stores_the_report(self, client, db):
        service = AnalysisService()
        github = MagicMock()
        github.fetch_repo_metadata = AsyncMock(
            return_value={"full_name": "octo/demo", "pushed_at": None}
        )
        github.fetch_languages = AsyncMock(return_value={"Python": 10})
        github.fetch_contributors = AsyncMock(return_value=[])
        github.fetch_contents = AsyncMock(return_value=[{"name": "README.md", "type": "file"}])
        github.fetch_recent_commits = AsyncMock(return_value=[])
        service.github = github
        use_service(service)

        events = read_events(client.post("/api/v1/analyze/stream", json={"url": "octo/demo"}))
        steps = [e.get("step") for e in events if e["event"] == "progress"]
        assert steps.count("fetch") == 7  # the start, then one per finished call
        assert steps[-3:] == ["analyze", "score", "save"]
        done = events[-1]
        assert done["event"] == "done"
        stored = db.query(Analysis).one()
        assert done["report_url"] == f"/analysis/{stored.id}"

    def test_is_documented_in_openapi_and_pages_are_not(self, client):
        schema = client.get("/openapi.json").json()
        stream = schema["paths"]["/api/v1/analyze/stream"]["post"]
        assert stream["tags"] == ["Analyses"]
        assert "application/x-ndjson" in stream["responses"]["200"]["content"]
        assert "/analysis/{analysis_id}" not in schema["paths"]
        assert "/history" not in schema["paths"]


# ---------------------------------------------------------------------------
# History filters
# ---------------------------------------------------------------------------


class TestHistoryFilters:
    def test_search_profile_and_sort(self, client, db):
        add_analysis(db, owner="psf", name="requests", score=77)
        add_analysis(db, owner="pallets", name="flask", score=81)
        add_analysis(db, owner="pallets", name="click", score=60, repo_type="personal")

        html = client.get("/history?q=PALLETS").text
        assert "pallets/flask" in html and "pallets/click" in html
        assert "psf/requests" not in html
        assert '2</span> of <span class="mono">3</span> reports match' in html

        html = client.get("/history?profile=personal").text
        assert "pallets/click" in html and "pallets/flask" not in html

        html = client.get("/history?sort=score_high").text
        assert html.index("pallets/flask") < html.index("psf/requests")
        assert html.index("psf/requests") < html.index("pallets/click")

    def test_no_match_offers_to_clear_filters(self, client, db):
        add_analysis(db)
        response = client.get("/history?q=nothing-like-this")
        assert response.status_code == 200
        assert b"No reports match" in response.content
        assert b'href="/history">Clear filters' in response.content

    def test_unknown_values_fall_back_instead_of_failing(self, client, db):
        add_analysis(db)
        response = client.get("/history?profile=banana&sort=sideways")
        assert response.status_code == 200
        assert b"psf/requests" in response.content

    def test_pages_keep_the_filters(self, client, db):
        for day in range(3):
            add_analysis(db, created_at=datetime(2026, 10, 1 + day))
        html = client.get("/history?limit=2&q=psf&sort=oldest").text
        assert 'href="/history?offset=2&amp;limit=2&amp;q=psf&amp;sort=oldest"' in html

    def test_every_sort_has_a_label(self):
        assert set(HISTORY_SORT_LABELS) == set(HISTORY_SORTS)


# ---------------------------------------------------------------------------
# Report page: evidence, fix plan, facts and score history
# ---------------------------------------------------------------------------


class TestReportDetail:
    def test_shows_each_check_and_what_each_fix_is_worth(self, client, db):
        analysis = add_analysis(db)
        html = client.get(f"/analysis/{analysis.id}").text
        # Evidence: the scorer's own sentence next to the check it belongs to
        assert 'id="dim-security"' in html
        assert "Missing dependency lockfile (e.g. requirements.txt, package-lock.json)." in html
        assert "None of <code>.env.example</code>" in html
        # Fix plan with points, and the projected score
        assert "Commit a dependency lockfile for reproducible deployments." in html
        assert ">+4</span>" in html
        assert (
            'goes from <strong class="mono">77</strong> to <strong class="mono">90</strong> (A)'
            in html
        )
        assert "- [ ] Commit a dependency lockfile" in html  # the copyable checklist
        # Facts derived from the stored metrics and findings
        assert "5 days before the scan" in html
        assert ">8</span>" in html  # CI workflows
        assert 'aria-label="Language mix: Python 99.4%, Makefile 0.6%"' in html

    def test_markdown_export_lists_the_same_fixes_with_their_points(self, client, db):
        analysis = add_analysis(db)
        md = client.get(f"/analysis/{analysis.id}/report.md").text
        assert (
            "1. Commit a dependency lockfile for reproducible deployments. " "(+4 points, security)"
        ) in md
        assert "(up to +6 points, activity)" in md
        assert "The file-level fixes add 13 points: 77 → 90 (A)." in md

    def test_score_history_lists_every_report_of_the_repository(self, client, db):
        add_analysis(db, score=70, created_at=datetime(2026, 9, 1))
        newest = add_analysis(db, score=77, created_at=datetime(2026, 10, 31))
        html = client.get(f"/analysis/{newest.id}").text
        assert "Score history" in html
        assert html.count('class="timeline-row') == 2

    def test_single_report_has_no_score_history(self, client, db):
        analysis = add_analysis(db)
        assert "Score history" not in client.get(f"/analysis/{analysis.id}").text

    def test_old_live_reports_offer_a_fresh_analysis_and_new_ones_do_not(self, client, db):
        old = add_analysis(db, owner="a", name="old", created_at=datetime(2026, 1, 1))
        fresh = add_analysis(
            db, owner="b", name="fresh", created_at=datetime.now(UTC).replace(tzinfo=None)
        )
        assert "Analyze again" in client.get(f"/analysis/{old.id}").text
        assert "Analyze again" not in client.get(f"/analysis/{fresh.id}").text


class TestCompareAndScoringCharts:
    def test_compare_draws_both_repositories_and_their_fixes(self, client, db):
        add_analysis(db, owner="psf", name="requests")
        add_analysis(db, owner="pallets", name="flask", score=81)
        html = client.get("/compare?a=psf/requests&b=pallets/flask").text
        assert 'class="radar-series series-a"' in html
        assert 'class="radar-series series-b"' in html
        assert html.count("Commit a dependency lockfile for reproducible deployments.") == 2

    def test_scoring_page_shows_where_the_points_come_from(self, client):
        html = client.get("/scoring").text
        assert "Where the 100 points come from" in html
        assert 'title="Security: 12 points"' in html
