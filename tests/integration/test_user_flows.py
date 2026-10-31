"""
Integration tests for user flows end to end: renamed repositories, the
"Analyze again" hand-off to the live pipeline, error states that point at the
right field, the report's score history and facts, and the compare page's
knowledge of stored reports (see docs/process-flows.md).

GitHub is never contacted: the analysis service is a mock where one is needed.
"""

import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.dependencies import get_analysis_service
from app.exceptions import RepositoryNotFoundError, TooManyAnalysesError, UpstreamServiceError
from app.models.db_models import Repository, RepositoryAlias
from app.repositories.db import Base, get_db
from app.services.repository_service import RepositoryService
from main import app
from tests.integration.conftest import override_get_db, test_engine
from tests.integration.test_progress_and_pages import add_analysis, use_service

app.dependency_overrides[get_db] = override_get_db
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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


def failing_service(error: Exception) -> MagicMock:
    service = MagicMock()
    service.run = AsyncMock(side_effect=error)
    use_service(service)
    return service


# ---------------------------------------------------------------------------
# Renamed repositories
# ---------------------------------------------------------------------------


class TestRenamedRepositories:
    def test_old_name_finds_the_report_stored_under_the_new_one(self, client, db):
        analysis = add_analysis(db, owner="Kludex", name="starlette", score=74)
        RepositoryService().record_rename(
            db, analysis.repository, "https://github.com/encode/starlette"
        )

        response = client.get("/repo/encode/starlette")
        assert response.status_code == 303
        assert response.headers["location"] == f"/analysis/{analysis.id}"
        assert "74/100" in client.get("/badge/encode/starlette.svg").text

    def test_reuse_window_follows_the_rename(self, db):
        analysis = add_analysis(
            db, owner="Kludex", name="starlette", created_at=datetime.now(UTC).replace(tzinfo=None)
        )
        svc = RepositoryService()
        svc.record_rename(db, analysis.repository, "https://github.com/encode/starlette")

        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        found = svc.find_recent_analysis(
            db, "https://github.com/ENCODE/Starlette", "library", since
        )
        assert found is not None and found.id == analysis.id

    def test_a_name_that_is_a_repository_again_stops_redirecting(self, db):
        old = add_analysis(db, owner="Kludex", name="starlette")
        svc = RepositoryService()
        svc.record_rename(db, old.repository, "https://github.com/encode/starlette")

        # Someone creates a new repository at the old address, and it is analyzed
        new_repo = Repository(
            owner="encode", name="starlette", url="https://github.com/encode/starlette"
        )
        db.add(new_repo)
        db.commit()
        svc.record_rename(db, new_repo, "https://github.com/encode/starlette")

        assert db.query(RepositoryAlias).count() == 0
        assert svc.resolve_url(db, "https://github.com/encode/starlette").endswith(
            "encode/starlette"
        )

    def test_compare_treats_the_old_and_new_names_as_one_repository(self, client, db):
        analysis = add_analysis(db, owner="Kludex", name="starlette")
        RepositoryService().record_rename(
            db, analysis.repository, "https://github.com/encode/starlette"
        )
        response = client.get("/compare?a=encode/starlette&b=Kludex/starlette")
        assert response.status_code == 400
        assert "Those are the same repository" in response.text


# ---------------------------------------------------------------------------
# "Analyze again" runs the live pipeline on the home page
# ---------------------------------------------------------------------------


class TestAnalyzeAgain:
    def test_report_links_to_the_home_page_with_autostart(self, client, db):
        old = add_analysis(db, created_at=datetime(2026, 1, 1), repo_type="personal")
        html = client.get(f"/analysis/{old.id}").text
        assert 'href="/?url=psf%2Frequests&amp;repo_type=personal&amp;autostart=1"' in html

    def test_example_report_offers_a_fresh_run_the_same_way(self, client, db):
        example = add_analysis(db, is_example=True)
        html = client.get(f"/analysis/{example.id}").text
        assert "Run a fresh analysis" in html
        assert "autostart=1" in html

    def test_home_page_prefills_the_form_and_asks_to_start(self, client):
        html = client.get("/?url=psf/requests&repo_type=personal&autostart=1").text
        assert 'value="psf/requests"' in html
        assert re.search(r'<option value="personal"\s+selected>', html)
        assert "data-autostart" in html

    def test_autostart_needs_a_repository_and_odd_values_are_ignored(self, client):
        assert "data-autostart" not in client.get("/?autostart=1").text
        response = client.get("/?url=psf/requests&autostart=yes&repo_type=banana")
        assert response.status_code == 200
        assert "data-autostart" not in response.text
        assert re.search(r'<option value="library"\s+selected>', response.text)


# ---------------------------------------------------------------------------
# Error states mark the field only when the input is at fault
# ---------------------------------------------------------------------------


class TestErrorStates:
    def test_unknown_repository_marks_the_field(self, client):
        failing_service(RepositoryNotFoundError("a", "b"))
        response = client.post("/analyze", data={"url": "a/b"})
        assert response.status_code == 404
        assert 'aria-invalid="true"' in response.text

    def test_server_side_failures_leave_the_field_alone(self, client):
        failing_service(TooManyAnalysesError(5, 600, 42))
        response = client.post("/analyze", data={"url": "psf/requests"})
        assert response.status_code == 429
        assert response.headers["retry-after"] == "42"
        assert 'aria-invalid="true"' not in response.text

        failing_service(UpstreamServiceError("network error"))
        response = client.post("/analyze", data={"url": "psf/requests"})
        assert response.status_code == 502
        assert 'aria-invalid="true"' not in response.text

    def test_compare_marks_the_side_that_is_wrong(self, client, db):
        add_analysis(db)
        html = client.get("/compare?a=psf/requests&b=not a repo").text
        field_b = re.search(r'<input id="compare-b"[^>]*>', html).group(0)
        field_a = re.search(r'<input id="compare-a"[^>]*>', html).group(0)
        assert 'aria-invalid="true"' in field_b
        assert 'aria-describedby="compare-error"' in field_b
        assert "aria-invalid" not in field_a

    def test_compare_marks_a_side_github_does_not_know(self, client, db):
        add_analysis(db)
        failing_service(RepositoryNotFoundError("ghost", "repo"))
        html = client.get("/compare?a=ghost/repo&b=psf/requests").text
        field_a = re.search(r'<input id="compare-a"[^>]*>', html).group(0)
        assert 'aria-describedby="side-error-a"' in field_a
        assert 'id="side-error-a"' in html


# ---------------------------------------------------------------------------
# Report details
# ---------------------------------------------------------------------------


def timeline_rows(html: str) -> list[str]:
    return re.findall(r'<a class="timeline-row[^"]*".*?</a>', html, flags=re.S)


class TestReportDetails:
    def test_score_history_rows_have_the_same_cells_with_or_without_the_example_tag(
        self, client, db
    ):
        add_analysis(db, is_example=True, created_at=datetime(2026, 9, 1))
        newest = add_analysis(db, created_at=datetime(2026, 10, 31))
        rows = timeline_rows(client.get(f"/analysis/{newest.id}").text)
        assert len(rows) == 2
        # One cell each: date, tags, bar, grade, score (the Example tag lives inside "tags")
        for row in rows:
            cells = re.findall(
                r'class="(mono timeline-date|timeline-tags|bar|grade-badge[^"]*|mono timeline-score)"',
                row,
            )
            assert len(cells) == 5, row
        assert "tag-example" in rows[1]
        assert "tag-example" not in rows[0]

    def test_rows_without_a_stored_grade_show_the_grade_of_their_score(self, client, db):
        older = add_analysis(db, score=58, created_at=datetime(2026, 9, 1))
        older.metrics.health_grade = None
        db.commit()
        newest = add_analysis(db, created_at=datetime(2026, 10, 31))
        html = client.get(f"/analysis/{newest.id}").text
        assert 'title="Grade C"' in html  # 58 is a C under the real grade scale
        history = client.get("/history").text
        assert history.count('title="Grade C"') == 1

    def test_last_push_shows_the_year_when_it_differs_from_the_scan(self, client, db):
        analysis = add_analysis(db, created_at=datetime(2026, 10, 31))
        analysis.metrics.last_pushed = datetime(2024, 11, 6)
        db.commit()
        html = client.get(f"/analysis/{analysis.id}").text
        assert ">Nov 2024<" in html
        assert "724 days before the scan" in html

    def test_last_push_in_the_same_year_shows_the_day(self, client, db):
        analysis = add_analysis(db, created_at=datetime(2026, 10, 31))
        assert ">Oct 26<" in client.get(f"/analysis/{analysis.id}").text

    def test_badge_snippets_use_the_reports_profile(self, client, db):
        analysis = add_analysis(db, repo_type="personal")
        html = client.get(f"/analysis/{analysis.id}").text
        assert "/badge/psf/requests.svg?profile=personal" in html

    def test_strengths_and_concerns_are_both_visible(self, client, db):
        analysis = add_analysis(db)
        html = client.get(f"/analysis/{analysis.id}").text
        assert "Key strengths" in html and "Areas of concern" in html
        assert 'role="tab" id="tab-strengths"' not in html


# ---------------------------------------------------------------------------
# Compare and history
# ---------------------------------------------------------------------------


class TestCompareAndHistory:
    def test_compare_form_knows_which_reports_are_stored(self, client, db):
        add_analysis(db)
        add_analysis(db, owner="pallets", name="flask", repo_type="personal")
        html = client.get("/compare").text
        assert "psf/requests:library" in html
        assert "pallets/flask:personal" in html

    def test_history_shows_the_date_and_utc_time(self, client, db):
        add_analysis(db, created_at=datetime(2026, 10, 31, 14, 5))
        html = client.get("/history").text
        assert ">Oct 31, 2026<" in html
        assert '<span class="mono">14:05</span> UTC' in html
