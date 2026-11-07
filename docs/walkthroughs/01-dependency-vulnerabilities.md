# Walkthrough 1: dependency and vulnerability scanning

## What it does and why it matters

ArchLens used to say how well a repository is kept (README, tests, CI, activity). It said nothing about the
libraries the repository depends on, which is where many real security problems come from.

Now every new analysis also:

1. reads the repository's dependency files and lists the **direct dependencies** per ecosystem, with the version and
   whether it is **pinned** (an exact version is known) or not;
2. checks every pinned version against **OSV.dev**, a free public database of known vulnerabilities (no API key);
3. shows each vulnerability with its **severity**, an **advisory link** and **the version to upgrade to**.

It appears in four places: the report page ("Dependencies" and "Known vulnerabilities" cards), the JSON API
(`dependency_scan`), the Markdown export and the CLI.

The **0-100 score formula is not changed**. Old scores stay comparable, and the report says so. A vulnerable
dependency is information to act on, not a reason to silently move a number people have already seen.

## How it works end to end

```
analysis starts
  -> six GitHub calls (one is the root file listing)
  -> scan_dependencies()                         app/services/dependency_service.py
       select_manifests(root listing)            which files exist? (no extra request)
       fetch_file_text() x 1..7                  app/services/github_service.py, raw file text
       parse_manifests()                         one pure parser per file type
       check_vulnerabilities()                   OSV: one batch request + one request per advisory
  -> DependencyScan stored as JSON               metrics.dependencies_json (Alembic migration a1c5e8f20b64)
  -> shown by
       report page   app/templates/_dependencies.html (included in results.html)
       JSON API      app/routers/api.py + app/schemas/schemas.py (DependencyScanResponse)
       Markdown      app/services/report_export.py
       CLI           app/cli.py (print_dependencies)
```

Details worth knowing:

- **Few requests.** The analysis already fetched the repository root listing, so we know which manifests exist for
  free. We only download files that exist, only in the root, at most three `requirements*.txt` plus `pyproject.toml`,
  `package.json`, `package-lock.json` and `go.mod`. Files over 1 MB (5 MB for the lockfile) are skipped. The raw
  media type (`Accept: application/vnd.github.raw+json`) returns the file text directly, so there is no base64
  step and large files work.
- **Pinned.** `requests==2.31.0` is pinned; `requests>=2` is not. For npm, `package-lock.json` gives the exact
  resolved version of each direct dependency, so `^4.17.0` with a lockfile entry of `4.17.15` is pinned at
  `4.17.15`. Go requirements always carry an exact version. Go lines marked `// indirect` are not direct
  dependencies and are left out.
- **OSV, two steps.** `POST /v1/querybatch` takes all packages in one request and returns only advisory ids.
  Then `GET /v1/vulns/{id}` per distinct advisory (max 40, 10 at a time) gives the summary, severity and affected
  ranges. The "fixed in" version is the lowest `fixed` event above the installed version.
- **Severity.** GitHub's own label if the advisory has one; otherwise the base score is computed from the CVSS v3
  vector (`cvss3_base_score`) and mapped to critical/high/medium/low; otherwise "unknown".
- **Duplicates.** One problem is often published under several ids (GHSA, PYSEC, CVE). Records of the same package
  that list each other as aliases are shown once (`_merge_duplicates`).
- **Graceful failure.** OSV down, slow or returning junk: the dependencies are still listed and the report says
  "Couldn't check". GitHub refusing the manifest requests: status `error`, "Analyze again later". A crash anywhere
  in the scan is caught in `AnalysisService.run`. None of these can fail an analysis.
- **Stored with the analysis** as one JSON column, like the other JSON columns in `metrics`. `NULL` means the
  report was stored before the feature existed (including the bundled examples), and the page says "Not scanned".

## Design choices and trade-offs

| Choice | Why | Cost |
|---|---|---|
| Root files only | Keeps GitHub requests to 1-7 extra per analysis (the demo has 60 an hour unauthenticated) | Monorepos with manifests in sub-folders show fewer dependencies |
| Direct dependencies only | Transitive ones need a resolver or a lockfile parser per ecosystem; direct ones are what the owner controls | Vulnerabilities in transitive packages are not found (except npm resolved versions are used for the direct ones) |
| Only pinned versions are checked | Without an exact version "is it vulnerable?" has no honest answer | Loose requirements are listed as "not pinned" instead of checked |
| Hand-written parsers | A few dozen lines each, easy to explain and test, no new dependencies | Exotic syntax (Poetry tables, `requirements` includes) is not read |
| JSON column, not new tables | Matches the existing design; the scan is always read as a whole, never queried by dependency | Cannot ask "which repositories use package X?" in SQL |
| OSV, not a paid scanner | Free, no key, covers PyPI, npm and Go with the same API | Depends on a third party; hence the "couldn't check" state |
| Score unchanged | Past scores remain comparable | A repository full of vulnerabilities can still score high |
| New `httpx` client per OSV check | Simple and easy to test | One extra TLS handshake per analysis |

## Limits

- Root directory only; at most seven files (three `requirements*.txt`, `pyproject.toml`, `package.json`,
  `package-lock.json`, `go.mod`); at most 200 pinned dependencies sent to OSV; at most 40 advisory
  look-ups (advisories beyond that are listed by id with severity "unknown").
- Python: `requirements*.txt` and `[project] dependencies` in `pyproject.toml`. Not Poetry, Pipenv, `setup.py`
  or optional dependency groups. Version comparison for "fixed in" is numeric, not full PEP 440.
- npm: dependencies and devDependencies; non-registry specs (git URLs) are listed as not pinned.
- Reports stored before this feature show "Not scanned" until the repository is analyzed again.
- A reused report (same repository within the hour) shows the scan from when it was made.

## Likely interview questions

1. **Why did you not change the score?** People compare scores over time and across repositories. Folding a new
   signal in would silently re-rank everything. It is shown separately and the report says it does not affect the
   score. It could become a profile option later.
2. **How do you keep GitHub requests low?** The root listing is already fetched for scoring, so I read the file
   names and sizes from it. I download only manifests that exist, only in the root, and cap the number.
3. **What happens when OSV is down?** The `httpx` call has an 8 second timeout and the whole stage 25 seconds. Any
   HTTP error, network error or malformed answer is caught and stored as `vulnerability_check = "unavailable"`.
   The page shows the dependencies and "Couldn't check". Tests cover a 503 and a connection error.
4. **Why batch queries?** One request for all packages instead of one per package. The batch answer only has ids,
   so I then fetch details per distinct advisory, concurrently but limited to 10 with a semaphore.
5. **How do you decide "pinned"?** Python: `==` or `===` with a version. npm: the version resolved in
   `package-lock.json`, or an exact version in `package.json`. Go: always. Anything else cannot be checked
   honestly.
6. **How is severity decided when OSV has no label?** I compute the CVSS v3 base score from the vector string with
   the published formula and map it to bands (9+, 7+, 4+, above 0). I tested it against known scores (9.8, 5.3,
   7.2). CVSS v4 vectors are shown as "unknown".
7. **Why store JSON instead of tables?** The data is read and written as a unit with the analysis and never
   filtered by dependency. It matches the existing JSON columns, and the migration is one nullable column.
8. **How did you test it without the network?** The parsers are pure functions. GitHub and OSV are replaced with
   `httpx.MockTransport`. One end-to-end test sends a request to the real FastAPI app, runs the real service with
   the fake GitHub and OSV, then checks the stored JSON, the API, the report page and the Markdown.
