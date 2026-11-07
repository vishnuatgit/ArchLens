import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.dependency_service import (
    Dependency,
    DependencyScan,
    Vulnerability,
    advisory_severity,
    check_vulnerabilities,
    cvss3_base_score,
    fixed_version,
    parse_go_mod,
    parse_package_json,
    parse_pyproject,
    parse_requirement,
    parse_requirements_txt,
    scan_dependencies,
    select_manifests,
)
from app.services.github_service import GitHubAPIError


class TestParsers:
    def test_requirements_pins_ranges_extras_markers_and_options(self):
        text = (
            "# comment\n"
            "-r other.txt\n"
            "Flask==2.3.2  # web\n"
            "requests[socks]>=2.0,<3\n"
            "Django_Rest.Framework === 3.14.0 ; python_version >= '3.9'\n"
            "numpy\n"
            "pytest==8.0 \\\n    --hash=sha256:abc\n"
        )
        found = {d.name: d for d in parse_requirements_txt(text, "requirements.txt")}
        assert set(found) == {"flask", "requests", "django-rest-framework", "numpy", "pytest"}
        assert found["flask"].version == "2.3.2" and found["flask"].pinned
        assert found["requests"].version is None and found["requests"].spec == ">=2.0,<3"
        assert found["django-rest-framework"].version == "3.14.0"
        assert not found["numpy"].pinned and found["numpy"].spec == ""
        assert found["pytest"].version == "8.0"

    def test_parse_requirement_ignores_blank_and_option_lines(self):
        assert parse_requirement("", "r.txt") is None
        assert parse_requirement("-e .", "r.txt") is None

    def test_pyproject_reads_project_dependencies_only(self):
        text = (
            '[project]\nname = "x"\ndependencies = ["httpx==0.27.0", "typer>=0.12"]\n'
            '[project.optional-dependencies]\ndev = ["pytest==8.0"]\n'
        )
        found = parse_pyproject(text)
        assert [(d.name, d.version) for d in found] == [("httpx", "0.27.0"), ("typer", None)]

    def test_package_json_uses_the_lockfile_for_resolved_versions(self):
        package = json.dumps(
            {
                "dependencies": {"express": "^4.18.0", "left-pad": "1.3.0"},
                "devDependencies": {"jest": "~29.0.0", "weird": "github:user/repo"},
            }
        )
        lock = json.dumps({"packages": {"": {}, "node_modules/express": {"version": "4.18.2"}}})
        found = {d.name: d for d in parse_package_json(package, lock)}
        assert found["express"].version == "4.18.2" and found["express"].spec == "^4.18.0"
        assert found["left-pad"].version == "1.3.0"  # exact in package.json itself
        assert found["jest"].version is None and found["jest"].dev
        assert found["weird"].version is None

    def test_package_json_reads_lockfile_v1(self):
        lock = json.dumps({"dependencies": {"express": {"version": "4.17.1"}}})
        found = parse_package_json('{"dependencies": {"express": "^4.0.0"}}', lock)
        assert found[0].version == "4.17.1"

    def test_go_mod_skips_indirect_requirements(self):
        text = (
            "module example.com/m\n\ngo 1.22\n\n"
            "require github.com/gin-gonic/gin v1.9.1\n"
            "require (\n\tgolang.org/x/text v0.3.0\n\tgithub.com/x/y v1.0.0 // indirect\n)\n"
        )
        found = parse_go_mod(text)
        assert [(d.name, d.version) for d in found] == [
            ("github.com/gin-gonic/gin", "v1.9.1"),
            ("golang.org/x/text", "v0.3.0"),
        ]


class TestSelectManifests:
    @staticmethod
    def listing(*names, size=100):
        return [{"name": n, "type": "file", "size": size} for n in names]

    def test_picks_known_manifests_from_the_root_listing(self):
        root = self.listing(
            "README.md", "requirements.txt", "requirements-dev.txt", "go.mod", "package.json"
        )
        root.append({"name": "requirements", "type": "dir", "size": 0})
        assert set(select_manifests(root)) == {
            "requirements.txt",
            "requirements-dev.txt",
            "go.mod",
            "package.json",
        }

    def test_lockfile_only_with_package_json_and_big_files_skipped(self):
        assert select_manifests(self.listing("package-lock.json")) == {}
        root = self.listing("package.json") + self.listing("package-lock.json", size=9_000_000)
        assert set(select_manifests(root)) == {"package.json"}

    def test_limits_the_number_of_requirements_files(self):
        root = self.listing(*(f"requirements-{i}.txt" for i in range(8)))
        assert len(select_manifests(root)) == 3


class TestSeverity:
    def test_cvss3_known_scores(self):
        assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
        assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L") == 5.3
        assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:L/I:L/A:N") == 7.2
        assert cvss3_base_score("CVSS:4.0/AV:N") is None
        assert cvss3_base_score("CVSS:3.1/AV:N") is None

    def test_label_from_github_then_from_vector(self):
        assert advisory_severity({"database_specific": {"severity": "MODERATE"}}) == "medium"
        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        record = {"severity": [{"type": "CVSS_V3", "score": vector}]}
        assert advisory_severity(record) == "critical"
        assert advisory_severity({}) == "unknown"


def record(events, name="jinja2", ecosystem="PyPI", **extra):
    return {
        "affected": [
            {
                "package": {"name": name, "ecosystem": ecosystem},
                "ranges": [{"type": "ECOSYSTEM", "events": events}],
            }
        ],
        **extra,
    }


def test_fixed_version_is_the_lowest_fix_above_the_installed_version():
    dep = Dependency("jinja2", "PyPI", "==2.1", "2.1", "r.txt")
    events = [
        {"introduced": "0"},
        {"fixed": "1.5"},
        {"introduced": "2.0"},
        {"fixed": "2.10"},
        {"fixed": "2.9"},
    ]
    assert fixed_version(record(events), dep) == "2.9"
    assert fixed_version(record([{"introduced": "0"}]), dep) is None
    assert fixed_version(record(events, name="other"), dep) is None


def osv_client(batch, records, fail_details=()):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/querybatch":
            return httpx.Response(200, json=batch(json.loads(request.content)))
        advisory_id = request.url.path.rsplit("/", 1)[1]
        if advisory_id in fail_details or advisory_id not in records:
            return httpx.Response(500)
        return httpx.Response(200, json=records[advisory_id])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestCheckVulnerabilities:
    deps = [
        Dependency("jinja2", "PyPI", "==2.1", "2.1", "requirements.txt"),
        Dependency("flask", "PyPI", ">=2", None, "requirements.txt"),
        Dependency("lodash", "npm", "^4", "4.17.15", "package.json"),
    ]

    async def test_only_pinned_dependencies_are_sent_and_duplicates_are_merged(self):
        sent = []

        def batch(body):
            sent.append(body["queries"])
            return {
                "results": [
                    {"vulns": [{"id": "GHSA-aaaa"}, {"id": "PYSEC-1"}, {"id": "GHSA-gone"}]},
                    {},
                ]
            }

        records = {
            "GHSA-aaaa": {
                "summary": "XSS",
                "aliases": ["CVE-1", "PYSEC-1"],
                "database_specific": {"severity": "HIGH"},
                **record([{"fixed": "2.9"}]),
            },
            "PYSEC-1": {"aliases": ["CVE-1", "GHSA-aaaa"], **record([{"fixed": "2.9"}])},
            "GHSA-gone": {"withdrawn": "2024-01-01T00:00:00Z"},
        }
        async with osv_client(batch, records) as client:
            found, checked = await check_vulnerabilities(self.deps, client)

        assert checked == 2
        assert [q["package"]["name"] for q in sent[0]] == ["jinja2", "lodash"]
        assert len(found) == 1  # PYSEC-1 is the same problem; GHSA-gone was withdrawn
        assert (found[0].id, found[0].severity, found[0].fixed) == ("GHSA-aaaa", "high", "2.9")
        assert found[0].url == "https://osv.dev/vulnerability/GHSA-aaaa"
        assert "Upgrade jinja2 to 2.9" in found[0].advice

    async def test_a_failed_detail_request_keeps_the_advisory_with_unknown_severity(self):
        def batch(body):
            return {"results": [{"vulns": [{"id": "GHSA-x"}]}, {}]}

        async with osv_client(batch, {}, fail_details={"GHSA-x"}) as client:
            found, _ = await check_vulnerabilities(self.deps, client)
        assert [(v.id, v.severity, v.fixed) for v in found] == [("GHSA-x", "unknown", None)]
        assert "No fixed version" in found[0].advice

    async def test_batch_failure_raises_for_the_caller_to_degrade(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        with pytest.raises(httpx.HTTPStatusError):
            await check_vulnerabilities(self.deps, client)

    async def test_nothing_pinned_makes_no_request(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: 1 / 0))
        assert await check_vulnerabilities([self.deps[1]], client) == ([], 0)


class TestScanDependencies:
    root = [{"name": "requirements.txt", "type": "file", "size": 20}]

    @staticmethod
    def github(text="jinja2==2.1\n"):
        github = MagicMock()
        github.fetch_file_text = AsyncMock(return_value=text)
        return github

    async def test_no_manifest_means_status_none_and_no_requests(self):
        github = self.github()
        scan = await scan_dependencies(github, "o", "r", [{"name": "README.md", "type": "file"}])
        assert scan.status == "none"
        github.fetch_file_text.assert_not_called()

    async def test_osv_down_degrades_to_could_not_check(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        scan = await scan_dependencies(self.github(), "o", "r", self.root, client)
        assert scan.status == "ok"
        assert scan.vulnerability_check == "unavailable"
        assert [d.name for d in scan.dependencies] == ["jinja2"]
        assert "could not be checked" in scan.summary_line

    async def test_osv_network_error_degrades_too(self):
        def boom(request):
            raise httpx.ConnectError("no network")

        client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        scan = await scan_dependencies(self.github(), "o", "r", self.root, client)
        assert scan.vulnerability_check == "unavailable"

    async def test_github_failure_gives_error_status_not_an_exception(self):
        github = MagicMock()
        github.fetch_file_text = AsyncMock(side_effect=GitHubAPIError("boom", 500))
        scan = await scan_dependencies(github, "o", "r", self.root)
        assert scan.status == "error" and scan.notes

    async def test_unparseable_manifest_is_skipped_with_a_note(self):
        root = [{"name": "package.json", "type": "file", "size": 5}]
        scan = await scan_dependencies(self.github("{not json"), "o", "r", root)
        assert scan.status == "ok" and scan.dependencies == []
        assert any("package.json" in note for note in scan.notes)

    async def test_only_unpinned_skips_the_check(self):
        scan = await scan_dependencies(self.github("flask>=2\n"), "o", "r", self.root)
        assert scan.vulnerability_check == "skipped"


def test_scan_round_trips_through_json():
    scan = DependencyScan(
        status="ok",
        manifests=["requirements.txt"],
        dependencies=[Dependency("jinja2", "PyPI", "==2.1", "2.1", "requirements.txt")],
        vulnerability_check="ok",
        vulnerabilities=[
            Vulnerability("GHSA-a", "jinja2", "PyPI", "2.1", "high", "XSS", "2.9", ("CVE-1",))
        ],
        checked=1,
    )
    again = DependencyScan.from_json(json.dumps(scan.to_dict()))
    assert again == scan
    assert DependencyScan.from_json(None) is None
    assert DependencyScan.from_json("not json") is None


def test_a_package_declared_in_two_files_is_listed_once_preferring_the_pinned_entry():
    from app.services.dependency_service import parse_manifests

    found, notes = parse_manifests(
        {
            "pyproject.toml": '[project]\ndependencies = ["flask>=2"]\n',
            "requirements.txt": "flask==2.3.2\n",
        }
    )
    assert notes == []
    assert [(d.name, d.version, d.source) for d in found] == [
        ("flask", "2.3.2", "requirements.txt")
    ]
