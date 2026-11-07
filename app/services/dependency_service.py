"""
Dependency scanning: which libraries a repository declares, and which pinned versions
have known vulnerabilities.

Two steps:
  1. Read the dependency manifests in the repository root through the GitHub contents API
     (requirements*.txt, pyproject.toml, package.json with package-lock.json, go.mod).
     The root listing the analysis already fetched says which files exist, so finding them
     costs no extra request; each manifest then costs one.
  2. Ask OSV.dev (free, no key) about every dependency whose exact version is known: one
     batch request for the list, then one request per advisory for its details.

None of this changes the 0-100 score. If OSV or the manifests cannot be read, the result
says so ("couldn't check") and the analysis carries on.
"""

import asyncio
import json
import logging
import math
import re
import tomllib
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from app.services.github_service import GitHubAPIError, GitHubService

logger = logging.getLogger("ArchLens.dependency_service")

# OSV's names for the ecosystems
PYPI = "PyPI"
NPM = "npm"
GO = "Go"
ECOSYSTEM_ORDER = (PYPI, NPM, GO)

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"
OSV_TIMEOUT = 8.0  # seconds per OSV request
MANIFEST_STAGE_TIMEOUT = 20.0  # seconds to read all manifests
OSV_STAGE_TIMEOUT = 25.0  # seconds for the whole OSV check
MAX_REQUIREMENTS_FILES = 3  # requirements.txt, requirements-dev.txt, ...
MAX_MANIFEST_BYTES = 1_000_000
MAX_LOCKFILE_BYTES = 5_000_000
MAX_CHECKED_DEPENDENCIES = 200  # distinct pinned dependencies sent to OSV
MAX_ADVISORY_LOOKUPS = 40  # advisory detail requests per analysis
DETAIL_CONCURRENCY = 10

SEVERITIES = ("critical", "high", "medium", "low", "unknown")

SCORE_NOTE = (
    "Dependencies and vulnerabilities are listed for information only. "
    "They do not change the 0-100 score, so reports stay comparable with earlier ones."
)


@dataclass(frozen=True)
class Dependency:
    name: str
    ecosystem: str
    spec: str  # what the manifest says: "==2.31.0", "^4.17.0", "v0.3.0", or "" for no constraint
    version: str | None  # the exact version when it is known, otherwise None
    source: str  # the manifest it came from
    dev: bool = False

    @property
    def pinned(self) -> bool:
        return self.version is not None


@dataclass(frozen=True)
class Vulnerability:
    id: str
    package: str
    ecosystem: str
    version: str
    severity: str  # one of SEVERITIES
    summary: str
    fixed: str | None  # the lowest later version that fixes it, when OSV says
    aliases: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"https://osv.dev/vulnerability/{self.id}"

    @property
    def advice(self) -> str:
        """What to do about it, in a few words."""
        if self.fixed:
            return f"Upgrade {self.package} to {self.fixed} or later"
        return f"No fixed version is listed yet for {self.package}; check the advisory"


@dataclass
class DependencyScan:
    """
    The result stored with an analysis.

    status: "ok" (manifests read), "none" (no supported manifest in the root) or
            "error" (GitHub would not give us the manifests).
    vulnerability_check: "ok", "unavailable" (OSV could not be reached) or
            "skipped" (no dependency has an exact version).
    """

    status: str = "none"
    manifests: list[str] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    vulnerability_check: str = "skipped"
    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    checked: int = 0  # dependencies sent to OSV
    notes: list[str] = field(default_factory=list)

    @property
    def pinned_count(self) -> int:
        return sum(1 for d in self.dependencies if d.pinned)

    @property
    def unpinned_count(self) -> int:
        return len(self.dependencies) - self.pinned_count

    def by_ecosystem(self) -> list[tuple[str, list[Dependency]]]:
        """Dependencies grouped per ecosystem, in a fixed order, each group sorted by name."""
        groups = []
        for ecosystem in ECOSYSTEM_ORDER:
            members = sorted(
                (d for d in self.dependencies if d.ecosystem == ecosystem),
                key=lambda d: (d.dev, d.name),
            )
            if members:
                groups.append((ecosystem, members))
        return groups

    @property
    def summary_line(self) -> str:
        """One sentence for the CLI, the Markdown export and the Action's comment."""
        if self.status == "none":
            return "No supported dependency file in the repository root."
        if self.status == "error":
            return "Dependencies could not be read."
        total = len(self.dependencies)
        text = f"{total} direct {'dependency' if total == 1 else 'dependencies'} ({self.pinned_count} pinned). "
        if self.vulnerability_check == "unavailable":
            return text + "Vulnerabilities could not be checked (OSV.dev did not answer)."
        if self.vulnerability_check == "skipped":
            return text + "None has an exact version, so no vulnerability check was possible."
        found = len(self.vulnerabilities)
        return text + (
            f"{found} known vulnerabilit{'y' if found == 1 else 'ies'} "
            f"in {self.checked} checked."
        )

    def severity_counts(self) -> dict[str, int]:
        counts = {severity: 0 for severity in SEVERITIES}
        for vulnerability in self.vulnerabilities:
            counts[vulnerability.severity] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "manifests": self.manifests,
            "dependencies": [asdict(d) | {"pinned": d.pinned} for d in self.dependencies],
            "vulnerability_check": self.vulnerability_check,
            "vulnerabilities": [asdict(v) | {"url": v.url} for v in self.vulnerabilities],
            "checked": self.checked,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DependencyScan":
        return cls(
            status=data.get("status", "none"),
            manifests=list(data.get("manifests", [])),
            dependencies=[
                Dependency(**{k: v for k, v in d.items() if k != "pinned"})
                for d in data.get("dependencies", [])
            ],
            vulnerability_check=data.get("vulnerability_check", "skipped"),
            vulnerabilities=[
                Vulnerability(
                    **{k: v for k, v in item.items() if k not in ("url", "aliases")},
                    aliases=tuple(item.get("aliases", [])),
                )
                for item in data.get("vulnerabilities", [])
            ],
            checked=data.get("checked", 0),
            notes=list(data.get("notes", [])),
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "DependencyScan | None":
        """Decodes the stored column; None means the report was stored before scanning existed."""
        if not raw:
            return None
        try:
            return cls.from_dict(json.loads(raw))
        except (ValueError, TypeError):
            logger.warning("Ignoring an unreadable stored dependency scan")
            return None


# ---------------------------------------------------------------------------
# Parsing the manifests (pure functions: text in, dependencies out)
# ---------------------------------------------------------------------------

_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
_EXACT_PIN = re.compile(r"^===?([A-Za-z0-9][A-Za-z0-9._+!-]*)$")
_EXACT_SEMVER = re.compile(r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")


def normalize_pypi_name(name: str) -> str:
    """PyPI treats '-', '_' and '.' alike and ignores case (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(line: str, source: str) -> Dependency | None:
    """Parses one PEP 508 requirement such as 'requests[socks]>=2.0; python_version<"3.12"'."""
    line = line.split(" #")[0].split(";")[0].split(" --")[0].strip()
    if not line or line.startswith(("-", "#")):  # options such as -r other.txt or -e .
        return None
    match = _REQUIREMENT.match(line)
    if not match:
        return None
    name, rest = match.groups()
    spec = rest.replace(" ", "").strip("()")
    exact = _EXACT_PIN.match(spec)
    return Dependency(
        name=normalize_pypi_name(name),
        ecosystem=PYPI,
        spec=spec,
        version=exact.group(1) if exact else None,
        source=source,
    )


def parse_requirements_txt(text: str, source: str) -> list[Dependency]:
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")  # lines continued with a backslash
    found = (parse_requirement(line, source) for line in text.splitlines())
    return [dependency for dependency in found if dependency]


def parse_pyproject(text: str, source: str = "pyproject.toml") -> list[Dependency]:
    """Reads [project] dependencies. Optional groups and Poetry's own tables are not read."""
    project = tomllib.loads(text).get("project", {})
    found = (parse_requirement(line, source) for line in project.get("dependencies", []))
    return [dependency for dependency in found if dependency]


def _locked_versions(lock_text: str | None) -> dict[str, str]:
    """name -> resolved version from package-lock.json (lockfile v1, v2 and v3)."""
    if not lock_text:
        return {}
    try:
        lock = json.loads(lock_text)
    except ValueError:
        return {}
    versions: dict[str, str] = {}
    for path, entry in (lock.get("packages") or {}).items():  # v2 and v3
        if path.startswith("node_modules/") and "version" in entry:
            versions[path.removeprefix("node_modules/")] = entry["version"]
    for name, entry in (lock.get("dependencies") or {}).items():  # v1 (and v2, for old npm)
        if isinstance(entry, dict) and "version" in entry:
            versions.setdefault(name, entry["version"])
    return versions


def parse_package_json(
    text: str, lock_text: str | None = None, source: str = "package.json"
) -> list[Dependency]:
    """
    Direct dependencies and devDependencies. A version counts as pinned when
    package-lock.json resolves it, or when package.json itself names an exact version.
    """
    package = json.loads(text)
    locked = _locked_versions(lock_text)
    found = []
    for group, dev in (("dependencies", False), ("devDependencies", True)):
        for name, spec in (package.get(group) or {}).items():
            if not isinstance(spec, str):
                continue
            exact = _EXACT_SEMVER.match(spec.strip())
            version = locked.get(name) or (exact.group(1) if exact else None)
            found.append(Dependency(name, NPM, spec.strip(), version, source, dev))
    return found


def parse_go_mod(text: str, source: str = "go.mod") -> list[Dependency]:
    """Direct requirements only: lines marked '// indirect' are left out."""
    found = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        indirect = "// indirect" in line
        line = line.split("//")[0].strip()
        if line == "require (":
            in_block = True
        elif in_block and line == ")":
            in_block = False
        elif in_block or line.startswith("require "):
            parts = line.removeprefix("require ").split()
            if len(parts) == 2 and not indirect:
                found.append(Dependency(parts[0], GO, parts[1], parts[1], source))
    return found


# ---------------------------------------------------------------------------
# Finding and reading the manifests
# ---------------------------------------------------------------------------

_REQUIREMENTS_NAME = re.compile(r"^requirements[\w.-]*\.txt$")


def select_manifests(root_contents: list[dict[str, Any]]) -> dict[str, int]:
    """
    Chooses the manifests to download from the root listing: name -> size in bytes.
    Files that are too large are left out (the lockfile alone may be up to 5 MB).
    """
    files = {
        item["name"]: int(item.get("size") or 0)
        for item in root_contents
        if isinstance(item, dict) and item.get("type") == "file" and "name" in item
    }
    chosen = {}
    for name in sorted(n for n in files if _REQUIREMENTS_NAME.match(n))[:MAX_REQUIREMENTS_FILES]:
        chosen[name] = files[name]
    for name in ("pyproject.toml", "package.json", "go.mod"):
        if name in files:
            chosen[name] = files[name]
    if "package.json" in files and "package-lock.json" in files:
        chosen["package-lock.json"] = files["package-lock.json"]
    return {
        name: size
        for name, size in chosen.items()
        if size <= (MAX_LOCKFILE_BYTES if name == "package-lock.json" else MAX_MANIFEST_BYTES)
    }


def parse_manifests(texts: dict[str, str]) -> tuple[list[Dependency], list[str]]:
    """Parses downloaded manifests; a file that cannot be parsed is skipped with a note."""
    dependencies: list[Dependency] = []
    notes: list[str] = []
    for name, text in texts.items():
        try:
            if name == "pyproject.toml":
                dependencies += parse_pyproject(text)
            elif name == "package.json":
                dependencies += parse_package_json(text, texts.get("package-lock.json"))
            elif name == "go.mod":
                dependencies += parse_go_mod(text)
            elif name != "package-lock.json":
                dependencies += parse_requirements_txt(text, name)
        except (ValueError, AttributeError, TypeError) as e:
            logger.warning(f"Could not parse {name}: {e}")
            notes.append(f"{name} could not be parsed and was skipped.")
    return _dedupe(dependencies), notes


def _dedupe(dependencies: list[Dependency]) -> list[Dependency]:
    """A package declared in several files (pyproject.toml and requirements.txt) is listed once."""
    chosen: dict[tuple[str, str, bool], Dependency] = {}
    for dependency in dependencies:
        key = (dependency.ecosystem, dependency.name, dependency.dev)
        if key not in chosen or (dependency.pinned and not chosen[key].pinned):
            chosen[key] = dependency
    return list(chosen.values())


# ---------------------------------------------------------------------------
# OSV.dev
# ---------------------------------------------------------------------------

_CVSS3_WEIGHTS = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PRIVILEGES = {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.5}}


def cvss3_base_score(vector: str) -> float | None:
    """Base score (0-10) of a CVSS v3.x vector such as 'CVSS:3.1/AV:N/AC:L/...'; None otherwise."""
    if not vector.startswith(("CVSS:3.0/", "CVSS:3.1/")):
        return None
    metrics = dict(part.split(":", 1) for part in vector.split("/")[1:] if ":" in part)
    try:
        scope = metrics["S"]
        weights = _CVSS3_WEIGHTS
        confidentiality, integrity, availability = (weights["C"][metrics[m]] for m in "CIA")
        exploitability = (
            8.22
            * weights["AV"][metrics["AV"]]
            * weights["AC"][metrics["AC"]]
            * _PRIVILEGES[scope][metrics["PR"]]
            * weights["UI"][metrics["UI"]]
        )
    except KeyError:
        return None
    impact_base = 1 - (1 - confidentiality) * (1 - integrity) * (1 - availability)
    if scope == "U":
        impact = 6.42 * impact_base
    else:
        impact = 7.52 * (impact_base - 0.029) - 3.25 * (impact_base - 0.02) ** 15
    if impact <= 0:
        return 0.0
    total = impact + exploitability if scope == "U" else 1.08 * (impact + exploitability)
    return math.ceil(round(min(total, 10), 5) * 10) / 10  # "round up" to one decimal


def severity_label(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low" if score > 0 else "unknown"


def advisory_severity(record: dict[str, Any]) -> str:
    """GitHub's own label when the advisory has one, otherwise computed from its CVSS v3 vector."""
    label = str((record.get("database_specific") or {}).get("severity", "")).lower()
    label = {"moderate": "medium"}.get(label, label)
    if label in SEVERITIES[:4]:
        return label
    for entry in record.get("severity") or []:
        score = cvss3_base_score(str(entry.get("score", "")))
        if score is not None:
            return severity_label(score)
    return "unknown"


def _version_key(version: str) -> tuple[int, ...]:
    """Numbers in a version, so '1.10.0' sorts after '1.9.0'. An approximation, not full PEP 440."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def fixed_version(record: dict[str, Any], dependency: Dependency) -> str | None:
    """The lowest version above the installed one that the advisory lists as fixed."""
    installed = _version_key(dependency.version or "")
    wanted = normalize_pypi_name(dependency.name)
    fixes = []
    for affected in record.get("affected") or []:
        package = affected.get("package") or {}
        if package.get("ecosystem") != dependency.ecosystem:
            continue
        if normalize_pypi_name(str(package.get("name", ""))) != wanted:
            continue
        for version_range in affected.get("ranges") or []:
            if version_range.get("type") in ("ECOSYSTEM", "SEMVER"):
                fixes += [e["fixed"] for e in version_range.get("events", []) if "fixed" in e]
    later = [fix for fix in fixes if _version_key(fix) > installed]
    return min(later, key=_version_key) if later else None


def _merge_duplicates(items: list[Vulnerability]) -> list[Vulnerability]:
    """
    One problem is often published under several ids (a GHSA, a PYSEC and a CVE). Records of
    the same package that list each other as aliases are shown once, under the GHSA id if any.
    """
    merged: list[tuple[set[str], Vulnerability]] = []
    for item in items:
        names = {item.id, *item.aliases}
        for index, (known, kept) in enumerate(merged):
            if known & names:
                best = (
                    item if item.id.startswith("GHSA") and not kept.id.startswith("GHSA") else kept
                )
                merged[index] = (known | names, best)
                break
        else:
            merged.append((names, item))
    return [item for _, item in merged]


@asynccontextmanager
async def _osv_session(client: httpx.AsyncClient | None):
    """Uses the client it is given (and leaves it open), or opens one for this check only."""
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=OSV_TIMEOUT) as owned:
            yield owned


async def check_vulnerabilities(
    dependencies: list[Dependency], client: httpx.AsyncClient | None = None
) -> tuple[list[Vulnerability], int]:
    """
    Looks up the dependencies that have an exact version. Returns (vulnerabilities, number
    of distinct dependencies checked). Raises httpx.HTTPError, ValueError or
    asyncio.TimeoutError when OSV cannot be used; the caller turns that into "couldn't check".
    """
    pinned: dict[tuple[str, str, str], Dependency] = {}
    for dependency in dependencies:
        if dependency.pinned:
            pinned.setdefault(
                (dependency.ecosystem, dependency.name, dependency.version), dependency
            )
    to_check = list(pinned.values())[:MAX_CHECKED_DEPENDENCIES]
    if not to_check:
        return [], 0

    async with _osv_session(client) as http:
        # 1. One request for every dependency: OSV answers with advisory ids only
        response = await http.post(
            OSV_BATCH_URL,
            json={
                "queries": [
                    {"package": {"name": d.name, "ecosystem": d.ecosystem}, "version": d.version}
                    for d in to_check
                ]
            },
        )
        response.raise_for_status()
        results = response.json()["results"]
        hits = [
            (dependency, [v["id"] for v in (result.get("vulns") or [])])
            for dependency, result in zip(to_check, results, strict=True)
        ]

        # 2. One request per distinct advisory (capped) for severity, summary and fixed version
        ids = list(dict.fromkeys(i for _, found in hits for i in found))[:MAX_ADVISORY_LOOKUPS]
        gate = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def fetch_record(advisory_id: str) -> tuple[str, dict[str, Any] | None]:
            async with gate:
                try:
                    detail = await http.get(OSV_VULN_URL + advisory_id)
                    detail.raise_for_status()
                    return advisory_id, detail.json()
                except (httpx.HTTPError, ValueError):
                    return advisory_id, None  # keep the id; only its details are missing

        records = dict(await asyncio.gather(*(fetch_record(i) for i in ids)))

    vulnerabilities = []
    for dependency, found in hits:
        items = []
        for advisory_id in found:
            record = records.get(advisory_id)
            if record is not None and record.get("withdrawn"):
                continue
            items.append(
                Vulnerability(
                    id=advisory_id,
                    package=dependency.name,
                    ecosystem=dependency.ecosystem,
                    version=dependency.version,
                    severity=advisory_severity(record) if record else "unknown",
                    summary=(record.get("summary") or "") if record else "",
                    fixed=fixed_version(record, dependency) if record else None,
                    aliases=tuple(record.get("aliases") or []) if record else (),
                )
            )
        vulnerabilities += _merge_duplicates(items)
    vulnerabilities.sort(key=lambda v: (SEVERITIES.index(v.severity), v.package, v.id))
    return vulnerabilities, len(to_check)


# ---------------------------------------------------------------------------
# The whole scan
# ---------------------------------------------------------------------------


async def scan_dependencies(
    github: GitHubService,
    owner: str,
    repo: str,
    root_contents: list[dict[str, Any]],
    osv_client: httpx.AsyncClient | None = None,
) -> DependencyScan:
    """
    Reads the manifests and checks them against OSV. Never raises for a GitHub or OSV problem:
    the scan records what could not be done, and the analysis carries on.
    """
    wanted = select_manifests(root_contents)
    if not wanted:
        return DependencyScan(status="none")

    try:
        async with asyncio.timeout(MANIFEST_STAGE_TIMEOUT):
            downloads = await asyncio.gather(
                *(github.fetch_file_text(owner, repo, name) for name in wanted)
            )
    except (GitHubAPIError, TimeoutError) as e:
        logger.warning(f"Could not read the manifests of {owner}/{repo}: {e}")
        return DependencyScan(
            status="error", notes=["GitHub did not return the dependency files, so none were read."]
        )
    texts = {name: text for name, text in zip(wanted, downloads, strict=True) if text}

    dependencies, notes = parse_manifests(texts)
    scan = DependencyScan(
        status="ok",
        manifests=[name for name in texts if name != "package-lock.json"],
        dependencies=dependencies,
        notes=notes,
    )
    if "package.json" in wanted and "package-lock.json" not in texts:
        scan.notes.append(
            "No package-lock.json was read, so only exact versions in package.json are checked."
        )

    try:
        async with asyncio.timeout(OSV_STAGE_TIMEOUT):
            scan.vulnerabilities, scan.checked = await check_vulnerabilities(
                dependencies, osv_client
            )
        scan.vulnerability_check = "ok" if scan.checked else "skipped"
    except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError) as e:
        logger.warning(f"OSV check failed for {owner}/{repo}: {e.__class__.__name__}: {e}")
        scan.vulnerability_check = "unavailable"
    return scan
