"""
Things that behave differently on PostgreSQL than on SQLite. These run on whichever database
the suite uses (SQLite by default, PostgreSQL when TEST_DATABASE_URL is set; see tests/db.py).
"""

import pytest
from fastapi.testclient import TestClient

from app.config import normalize_database_url
from app.repositories.db import Base, get_db
from main import app
from tests.integration.conftest import override_get_db, test_engine
from tests.integration.test_progress_and_pages import add_analysis

app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)


@pytest.fixture()
def client():
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("analysis_id", [2**31, 2**40, 2**63 - 1, 2**63, 10**30])
def test_ids_beyond_the_column_range_are_not_found_rather_than_a_server_error(client, analysis_id):
    # PostgreSQL integers are 32 bits and raise "integer out of range" instead of finding nothing
    assert client.get(f"/analysis/{analysis_id}").status_code == 404
    assert client.get(f"/api/v1/analyses/{analysis_id}").status_code == 404
    assert client.get(f"/analysis/{analysis_id}/report.md").status_code == 404


def test_largest_valid_id_is_looked_up_normally(client):
    assert client.get(f"/analysis/{2**31 - 1}").status_code == 404


def test_lookups_ignore_case_and_history_search_treats_wildcards_literally():
    from tests.integration.conftest import TestSessionLocal

    with TestSessionLocal() as db:
        add_analysis(db, owner="Psf", name="Requests")
        add_analysis(db, owner="pallets", name="flask")
        db.commit()
    client = TestClient(app, follow_redirects=False)
    assert client.get("/repo/PSF/requests").status_code == 303
    literal_percent = client.get("/history?q=%25").text  # "%" is not a wildcard
    assert "flask" not in literal_percent and "Requests" not in literal_percent
    page = client.get("/history?q=PSF/req").text
    assert "Requests" in page and "flask" not in page


def test_history_sorts_and_filters_work(client):
    from tests.integration.conftest import TestSessionLocal

    with TestSessionLocal() as db:
        add_analysis(db, owner="b", name="two", score=40)
        add_analysis(db, owner="a", name="one", score=90, repo_type="personal")
        db.commit()
    for sort in ("newest", "oldest", "score_high", "score_low", "name"):
        assert client.get(f"/history?sort={sort}").status_code == 200
    body = client.get("/api/v1/analyses?repo_type=personal&min_score=50").json()
    assert body["total"] == 1 and body["items"][0]["repo_name"] == "one"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        (
            "postgresql://u:p@host:5432/db?sslmode=require",
            "postgresql+psycopg://u:p@host:5432/db?sslmode=require",
        ),
        ("postgresql+psycopg://u@host/db", "postgresql+psycopg://u@host/db"),
        ("sqlite:///./ArchLens.db", "sqlite:///./ArchLens.db"),
    ],
)
def test_database_urls_are_pointed_at_the_psycopg_driver(url, expected):
    assert normalize_database_url(url) == expected
