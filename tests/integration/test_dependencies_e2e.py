"""
End to end: a request to the real app runs the real AnalysisService, which reads manifests
from a fake GitHub and asks a fake OSV, stores the scan, and the stored result is rendered
as an API response, a report page and a Markdown export. No network is used.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.dependencies import get_analysis_service
from app.models.db_models import Metric
from app.repositories.db import Base, get_db
from app.services.analysis_service import AnalysisService
from main import app
from tests.integration.conftest import override_get_db, test_engine
from tests.integration.test_progress_and_pages import use_service

app.dependency_overrides[get_db] = override_get_db
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

REQUIREMENTS = "jinja2==2.1\nflask>=2.0\n"
VECTOR = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"


def fake_github(root_files, files):
    """A GitHub API that serves one small repository."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/widget":
            return httpx.Response(
                200,
                json={
                    "full_name": "acme/widget",
                    "stargazers_count": 5,
                    "size": 100,
                    "pushed_at": "2026-11-01T00:00:00Z",
                },
            )
        if path == "/repos/acme/widget/languages":
            return httpx.Response(200, json={"Python": 1000})
        if path == "/repos/acme/widget/contributors":
            return httpx.Response(200, json=[{"login": "a"}])
        if path == "/repos/acme/widget/commits":
            return httpx.Response(200, json=[])
        if path == "/repos/acme/widget/contents/":
            return httpx.Response(
                200, json=[{"name": n, "type": "file", "size": 50} for n in root_files]
            )
        name = path.removeprefix("/repos/acme/widget/contents/")
        if name in files:
            return httpx.Response(200, text=files[name])
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def fake_osv(down=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if down:
            return httpx.Response(503)
        if request.url.path == "/v1/querybatch":
            queries = json.loads(request.content)["queries"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        (
                            {"vulns": [{"id": "GHSA-xxxx-yyyy-zzzz"}]}
                            if q["package"]["name"] == "jinja2"
                            else {}
                        )
                        for q in queries
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "GHSA-xxxx-yyyy-zzzz",
                "summary": "Sandbox escape in Jinja2",
                "aliases": ["CVE-2024-0001"],
                "severity": [{"type": "CVSS_V3", "score": VECTOR}],
                "affected": [
                    {
                        "package": {"name": "Jinja2", "ecosystem": "PyPI"},
                        "ranges": [{"type": "ECOSYSTEM", "events": [{"fixed": "2.11.3"}]}],
                    }
                ],
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    app.dependency_overrides.pop(get_analysis_service, None)


def install_service(root_files, files, osv_down=False) -> AnalysisService:
    service = AnalysisService(osv_client=fake_osv(osv_down))
    service.github._client = fake_github(root_files, files)
    use_service(service)
    return service


def analyze(client) -> dict:
    response = client.post("/api/v1/analyze", json={"url": "acme/widget"})
    assert response.status_code == 201, response.text
    return response.json()


def test_analysis_to_api_page_and_markdown():
    install_service(["README.md", "requirements.txt"], {"requirements.txt": REQUIREMENTS})
    client = TestClient(app)
    report = analyze(client)

    scan = report["dependency_scan"]
    assert scan["status"] == "ok" and scan["vulnerability_check"] == "ok"
    assert scan["manifests"] == ["requirements.txt"]
    assert {d["name"]: d["pinned"] for d in scan["dependencies"]} == {
        "jinja2": True,
        "flask": False,
    }
    (vuln,) = scan["vulnerabilities"]
    assert (vuln["id"], vuln["severity"], vuln["fixed"]) == (
        "GHSA-xxxx-yyyy-zzzz",
        "critical",
        "2.11.3",
    )
    assert vuln["url"] == "https://osv.dev/vulnerability/GHSA-xxxx-yyyy-zzzz"

    # Stored with the analysis
    with TestSessionLocal() as db:
        stored = json.loads(db.query(Metric).one().dependencies_json)
    assert stored["vulnerabilities"][0]["id"] == "GHSA-xxxx-yyyy-zzzz"

    # The same data, read back from storage through the other endpoints
    assert client.get(f"/api/v1/analyses/{report['id']}").json()["dependency_scan"] == scan
    page = client.get(f"/analysis/{report['id']}").text
    assert "Known vulnerabilities" in page and "GHSA-xxxx-yyyy-zzzz" in page
    assert "Upgrade jinja2 to 2.11.3 or later" in page
    assert "do not change the 0" in page
    markdown = client.get(f"/api/v1/analyses/{report['id']}/markdown").text
    assert "## Dependencies" in markdown and "## Known vulnerabilities" in markdown
    assert "upgrade to 2.11.3" in markdown
    assert client.get(f"/analysis/{report['id']}/report.md").status_code == 200


def test_score_does_not_depend_on_dependencies():
    scores = []
    for root_files, files in (
        (["README.md", "requirements.txt"], {"requirements.txt": "# nothing"}),
        (["README.md", "requirements.txt"], {"requirements.txt": REQUIREMENTS}),
    ):
        install_service(root_files, files)
        scores.append(analyze(TestClient(app))["score"])
    assert scores[0] == scores[1]


def test_osv_outage_still_gives_a_report_that_says_it_could_not_check():
    install_service(["requirements.txt"], {"requirements.txt": REQUIREMENTS}, osv_down=True)
    client = TestClient(app)
    report = analyze(client)
    assert report["dependency_scan"]["vulnerability_check"] == "unavailable"
    assert len(report["dependency_scan"]["dependencies"]) == 2
    page = client.get(f"/analysis/{report['id']}").text
    assert "Couldn&rsquo;t check" in page
    assert "Could not check" in client.get(f"/api/v1/analyses/{report['id']}/markdown").text


def test_repository_without_manifests_has_a_clear_empty_state():
    install_service(["README.md"], {})
    client = TestClient(app)
    report = analyze(client)
    assert report["dependency_scan"]["status"] == "none"
    assert "No supported dependency file" in client.get(f"/analysis/{report['id']}").text


def test_report_stored_before_scanning_says_so():
    from tests.integration.test_progress_and_pages import add_analysis

    with TestSessionLocal() as db:
        analysis = add_analysis(db)
        db.commit()
        analysis_id = analysis.id
    client = TestClient(app)
    assert client.get(f"/api/v1/analyses/{analysis_id}").json()["dependency_scan"] is None
    assert "Not scanned" in client.get(f"/analysis/{analysis_id}").text
    assert "Not scanned" in client.get(f"/api/v1/analyses/{analysis_id}/markdown").text


def test_stream_reports_a_dependencies_step():
    install_service(["requirements.txt"], {"requirements.txt": REQUIREMENTS})
    response = TestClient(app).post("/api/v1/analyze/stream", json={"url": "acme/widget"})
    events = [json.loads(line) for line in response.text.splitlines()]
    deps = [e for e in events if e.get("step") == "dependencies" and "vulnerabilities" in e]
    assert deps and deps[0]["vulnerabilities"] == 1
    assert events[-1]["event"] == "done"
