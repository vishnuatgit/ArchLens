# ArchLens

**Know how healthy any GitHub repo is, and what to fix first.** It scores any public repository's engineering health out of 100.

A FastAPI web app, REST API and CLI. It reads a repository's metadata and dependency files through the GitHub REST API (it never clones code), scores it across seven dimensions, explains every point, and stores every new analysis in SQLite so reports can be revisited, compared and shared.

[![CI](https://github.com/vishnuatgit/ArchLens/actions/workflows/ci.yml/badge.svg)](https://github.com/vishnuatgit/ArchLens/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Live demo:** [archlens-xhxr.onrender.com](https://archlens-xhxr.onrender.com) (free hosting: the first visit can take about a minute to wake it up) · REST API docs at `/docs` · [How it works](#how-it-works) · [Process flows](docs/process-flows.md)

![ArchLens report for pallets/werkzeug: a score gauge at 85 out of 100, grade A, an executive summary with 13 points within reach, and repository facts such as stars, last push and CI workflows](docs/screenshots/report.png)

<p>
  <img src="docs/screenshots/home.png" alt="ArchLens home page: the analysis form, the How it works steps that light up during an analysis, and an example report" width="72%" />
  <img src="docs/screenshots/report-mobile.png" alt="The same report on a phone, in the light theme" width="24%" />
</p>

Checking a repository by hand (license? tests? CI? recent commits? open issues?) means ten minutes of clicking around. ArchLens runs that checklist in one request, shows the evidence behind every point, and turns what is missing into a prioritised list of fixes.

It is built to run on a free host such as Render's free tier, where the first visit after a quiet spell is slow while the service wakes up and the database resets when the service restarts. Three example reports (`psf/requests`, `pallets/flask` and this repository) are then loaded again, labelled with the date they were captured, so the site is never empty.

---

## Features

- **Score and grade.** A 0–100 score across seven dimensions (documentation, activity, organization, community, maintainability, security, code quality), a letter grade from A+ to F, a health tier and a one-paragraph summary.
- **Live progress.** The home page's "How it works" steps (fetch, check 7 dimensions, score, suggest) light up as the analysis runs, driven by real events streamed from the server as each of the six GitHub calls finishes. A reused report is marked as reused rather than re-run, a failed step says why ("Repository not found", "GitHub did not answer"), and a slow GitHub is announced. A report's "Analyze again" runs through the same live steps.
- **Evidence for every point.** Each dimension opens to show its checks: passed, partial, missing, given or not scored, with what the scorer found (for example "Found 8 GitHub Actions workflow(s).") and the points earned.
- **What to fix first, with points.** Every missing check becomes a fix with the points it would add (`+4` for adding a file, "up to +6" for things like commit activity), exact fixes first, and the score and grade they would lead to. Copy it as a Markdown checklist.
- **Dependencies and known vulnerabilities.** The report lists the repository's direct dependencies per ecosystem (Python from `requirements*.txt` and `pyproject.toml`, npm from `package.json` with `package-lock.json`, Go from `go.mod`), says which are pinned to an exact version, and checks the pinned ones against [OSV.dev](https://osv.dev) (free, no key). Each vulnerability shows its severity, advisory link and the version to upgrade to. If OSV is down the report says "couldn't check" and the analysis still succeeds. This is shown in the report page, the JSON API (`dependency_scan`), the Markdown export and the CLI, and it does **not** change the 0-100 score, so older scores stay comparable. Only the repository root is read (no sub-folders), at most seven files (three `requirements*.txt`, `pyproject.toml`, `package.json`, `package-lock.json`, `go.mod`), so it costs up to seven extra GitHub requests.
- **Charts from real data.** A score gauge, a radar chart of the dimension profile, dimension bars, a language bar in GitHub's language colours, and a score history when a repository has been analyzed more than once.
- **Compare two repositories** side by side at `/compare?a=owner/repo&b=owner/repo`: overlaid radar charts, a dimension table with differences, and each one's top fixes. Stored reports are reused, so comparing known repositories costs no GitHub requests.
- **Share.** Copy a link, use the stable `/repo/{owner}/{repo}` permalink, export Markdown (copy, download or `GET /api/v1/analyses/{id}/markdown`), or add a README badge (`/badge/{owner}/{repo}.svg?profile=…`, never calls GitHub) with Markdown, HTML or URL snippets.
- **Renamed repositories.** GitHub follows renames and transfers; ArchLens stores the report under the new name and remembers the old one, so the old name's permalink, badge and reuse window still find it.
- **History** of every stored report, searchable by name, filterable by profile and sortable by date, score or name.
- **Scoring you can check.** The `/scoring` page lists every check, the files it looks for and its points under each profile. It is generated from the scorer's own constants, and tests run the real scorer against it and against the report's evidence, so the explanation cannot drift from the code.
- **Three profiles.** *Library* applies every check; *Personal* skips checks that mostly matter for shared projects; *Enterprise* does not judge popularity.
- **Web app, REST API and CLI** on one service layer. `archlens analyze psf/requests` prints the same report in a terminal.
- **Built for a free host.** A report of the same repository and profile from the last hour is reused, each visitor can start 5 new analyses per 10 minutes (with a countdown in the UI; an analysis that fails because GitHub is down or out of quota is given back), a failed GitHub call cancels the rest, and bundled example reports refill an empty database.
- **Polished front end, no build step.** Dark and light themes (following the system setting until you pick one), keyboard access and visible focus, screen-reader announcements for progress and copy actions, reduced-motion support, and layouts from 360 px phones to wide screens. The form still works without JavaScript.

## How it works

```mermaid
flowchart TD
    IN["Web form, REST API or CLI<br/>owner/repo or a GitHub URL"] --> V["Validate and normalise the input"]
    V --> C{"Same repository and profile<br/>analyzed in the last hour?"}
    C -- yes --> R["Report page"]
    C -- no --> L["Per-visitor rate limit"]
    L --> F["Fetch repo metadata<br/>6 read-only GitHub API calls, run concurrently"]
    F --> D["Read root dependency files, check pinned<br/>versions on OSV.dev (never fails the analysis)"]
    D --> S["Check 7 dimensions, then score and grade<br/>(MetricsService, rules as constants)"]
    S --> DB[("SQLite")]
    DB --> R
    R --> N["Evidence per check, fixes with points,<br/>Markdown export, README badge, compare"]
    F -. progress events .-> UI["Home page pipeline<br/>(POST /api/v1/analyze/stream)"]
    S -. progress events .-> UI
```

1. **Fetch repo metadata.** `GitHubService` reads repository stats, the root file listing, languages, contributors, commits from the last 30 days and the workflow folder, using one shared `httpx.AsyncClient` and `asyncio.gather` (if one call fails, the others are cancelled). It never clones the repository or downloads source files. Afterwards `dependency_service.py` downloads the dependency files found in the root (at most seven) and asks OSV.dev about the pinned versions; this does not change the score.
2. **Check 7 dimensions.** `MetricsService` looks for things like a README, license, test folder, CI workflows, lockfile, `SECURITY.md`, linter and type-checker config, recent commits and open issues.
3. **Score and grade.** Points add up to 100 and map to a grade (A+ is 95 and above, F is below 35) and a tier (Strong Codebase, Moderate Health, Needs Optimization).
4. **Suggest next steps.** Each failed check adds a finding and, where there is an obvious fix, a recommendation. The report lines every finding up with its check and ranks the fixes by the points they add.

`AnalysisService.run()` reports each step to a progress callback; `POST /api/v1/analyze/stream` forwards those events to the browser as newline-delimited JSON. Every user and system flow, with diagrams, files, functions and error paths, is described in **[docs/process-flows.md](docs/process-flows.md)**.

## Tech stack

| Layer | Choice |
| :--- | :--- |
| Language | Python 3.11+ |
| Web framework | FastAPI (async), server-rendered Jinja2 templates |
| GitHub client | httpx `AsyncClient`, shared for the app's lifetime |
| Storage | SQLite by default (PostgreSQL optional) via SQLAlchemy 2, migrations with Alembic |
| Vulnerability data | OSV.dev (free API, no key; failures degrade to "couldn't check") |
| CLI | Typer and Rich |
| Front end | Plain CSS, inline SVG charts and one vanilla JavaScript file, no build step |
| Quality | pytest (GitHub mocked, no network), Ruff, Black, GitHub Actions |
| Deployment | Multi-stage Docker image running as a non-root user, Render Blueprint |

## Run locally

Requires Python 3.11 or newer.

```bash
git clone https://github.com/vishnuatgit/ArchLens.git
cd ArchLens

python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\activate

pip install -r requirements.txt    # the app
pip install -e .                   # optional: the `archlens` command

alembic upgrade head               # create the SQLite schema
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000>. On first start the empty database is filled with the example reports from `app/seed/examples.json` (set `SEED_EXAMPLES=false` to skip this).

Without a token GitHub allows 60 API requests per hour, which is five to ten analyses (each uses six requests, plus one for each dependency file it finds). A token raises that to 5,000:

```bash
export GITHUB_TOKEN="your_token"       # Windows (PowerShell): $env:GITHUB_TOKEN="your_token"
```

From the command line:

```bash
archlens analyze psf/requests
archlens analyze https://github.com/pallets/flask --profile personal
archlens analyze psf/requests --format json --min-score 70   # machine-readable; exit code 2 if below 70
archlens analyze psf/requests --format markdown --output-dir out/   # also writes report.md, result.json, comment.md
```

`--format` is `rich` (default), `markdown` or `json`; the last two print only the report on stdout and send messages to stderr. Exit codes: `0` success, `1` the analysis failed, `2` the score is below `--min-score`.

### Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./ArchLens.db` | SQLAlchemy database URL. `postgresql://` and `postgres://` URLs work too (see [PostgreSQL](#postgresql-optional)) |
| `GITHUB_TOKEN` | unset | Optional GitHub token; raises the API limit from 60 to 5,000 requests per hour |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `ANALYSIS_CACHE_MINUTES` | `60` | Reuse a report of the same repository and profile created within this many minutes (`0` disables) |
| `ANALYSIS_RATE_LIMIT` | `5` | New analyses each client (by IP) may start per window (`0` disables) |
| `ANALYSIS_RATE_WINDOW_SECONDS` | `600` | Length of that rate-limit window |
| `SEED_EXAMPLES` | `true` | Load the example reports into an empty database on startup |

Copy `.env.example` to `.env` to set these locally. `python scripts/build_examples.py` regenerates the bundled example reports from live analyses.

### PostgreSQL (optional)

SQLite is the default and needs nothing. To run on PostgreSQL instead, install the driver and point `DATABASE_URL` at it; `postgresql://` and `postgres://` URLs (what Neon, Render and Heroku hand out) are accepted and switched to the `psycopg` driver automatically.

```bash
docker compose up -d db                       # PostgreSQL 16 on localhost:5432 (docker-compose.yml)
pip install -e ".[postgres]"
export DATABASE_URL=postgresql://archlens:archlens@localhost:5432/archlens
alembic upgrade head
uvicorn main:app
```

The same suite runs against PostgreSQL by setting `TEST_DATABASE_URL` (the tests create and drop their own tables, so use a throwaway database):

```bash
TEST_DATABASE_URL=postgresql://archlens:archlens@localhost:5432/archlens pytest
```

CI runs it both ways: the normal jobs use SQLite, and a `test-postgres` job starts a PostgreSQL 16 service container, applies the migrations, rolls them back and applies them again, then runs the whole suite. Running on PostgreSQL turned up one SQLite-only assumption (an id larger than 2^31 raised a database error instead of "not found"), which is fixed and tested.

## GitHub Action

ArchLens ships a composite GitHub Action (`action.yml` at the repository root). It installs ArchLens from this repository, analyzes a repository with the workflow's own `GITHUB_TOKEN`, writes the Markdown report to the job summary, exposes outputs, can fail the job below a minimum score and can keep one comment up to date on pull requests.

```yaml
name: Repository health
on:
  pull_request:
  schedule:
    - cron: "0 6 * * 1"

permissions:
  contents: read
  pull-requests: write   # only needed for comment: true

jobs:
  archlens:
    runs-on: ubuntu-latest
    steps:
      - uses: vishnuatgit/ArchLens@main
        id: health
        with:
          min-score: 60        # optional: fail the job below this score
          comment: true        # optional: one comment on pull requests, updated in place
      - run: echo "Score ${{ steps.health.outputs.score }} (${{ steps.health.outputs.grade }}), ${{ steps.health.outputs.vulnerabilities }} known vulnerabilities"
```

| Input | Default | Meaning |
| :--- | :--- | :--- |
| `repository` | the current repository | `owner/name` to analyze |
| `profile` | `library` | `library`, `personal` or `enterprise` |
| `min-score` | empty (never fails) | fail the job when the score is lower |
| `comment` | `false` | on `pull_request` events, post or update a single ArchLens comment (score, grade, top fixes, dependency summary) |
| `github-token` | `github.token` | token used to read repository metadata |
| `python-version` | `3.11` | Python used to run ArchLens |

Outputs: `score`, `grade`, and `vulnerabilities` (known vulnerabilities in pinned dependencies; empty when they could not be checked). Notes: use an Ubuntu runner; pull requests from forks get a read-only token, so the comment is skipped with a warning and the rest still works; the score describes the repository's metadata, not the pull request's diff. This repository runs the action on itself weekly and on demand (`.github/workflows/archlens-health.yml`). Details in [docs/walkthroughs/02-github-action.md](docs/walkthroughs/02-github-action.md).

## Tests

The same checks CI runs:

```bash
pip install -r requirements-dev.txt
pytest --cov=app tests/
ruff check app tests
black --check app tests
```

Unit tests cover the scorer, the dependency parsers and OSV lookup (with a faked OSV), `action.yml`, the scoring page generator (it runs the real scorer against the page's numbers), the report evidence (it runs the real scorer over about 900 generated repositories and checks every dimension adds up), the fix plan, the progress events, cancelling the other GitHub calls when one fails, the charts, the badge, the Markdown export, the GitHub client, the rate limiter (including refunds) and the CLI. Integration tests drive every page and API endpoint, including the progress stream, renamed repositories, the "Analyze again" hand-off and the error states, through FastAPI's `TestClient` with GitHub mocked, so the suite needs no network.

## Performance

Measured with [Locust](https://locust.io) against a local server that serves stored reports only, so no request reaches GitHub (the server log confirmed no analysis ran and no call to `api.github.com` was made). These are numbers from one laptop, not a promise about Render's free instance, which has less CPU and sleeps when idle.

**Method.** The database is seeded by `tests/load/seed_reports.py` with 60 repositories and 180 stored reports (every third one with a dependency scan). The server starts with the same command as `render.yaml` and the Dockerfile, with one uvicorn process on SQLite and default logging. Locust runs on the same machine for 60 seconds with 20 and then 50 simulated visitors (ramp of 10 users a second, 0.2 to 1 second of think time between actions), each repeatedly picking a random action: report page (weight 6), badge (4), history page (3), API list (3), API detail (2), repository permalink, Markdown export and a stored-report comparison (1 each). Every response must be HTTP 200.

```bash
export DATABASE_URL=sqlite:///./load.db SEED_EXAMPLES=false
alembic upgrade head && python tests/load/seed_reports.py
alembic upgrade head && uvicorn main:app --host 127.0.0.1 --port 8811     # the Render start command
locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8811 --csv load
```

**Results** (milliseconds; 0 failed requests in both runs):

| Endpoint | 20 users p50 | p95 | max | 50 users p50 | p95 | max |
| :--- | --: | --: | --: | --: | --: | --: |
| `GET /analysis/{id}` (report page) | 19 | 49 | 172 | 100 | 340 | 1,170 |
| `GET /history` | 41 | 92 | 489 | 240 | 550 | 1,249 |
| `GET /api/v1/analyses` (list) | 38 | 91 | 185 | 250 | 550 | 1,199 |
| `GET /api/v1/analyses/{id}` | 10 | 37 | 81 | 73 | 340 | 1,194 |
| `GET /badge/{owner}/{repo}.svg` | 10 | 30 | 141 | 58 | 270 | 882 |
| `GET /compare` (stored reports) | 20 | 84 | 146 | 110 | 390 | 1,045 |
| `GET /repo/{owner}/{repo}` (redirect to newest) | 26 | 65 | 131 | 140 | 480 | 2,007 |
| `GET /api/v1/analyses/{id}/markdown` | 10 | 37 | 47 | 65 | 250 | 903 |
| **All requests** | **21** | **79** | **1,120** | **120** | **510** | **2,467** |
| Requests per second | 31.7 | | | 62.0 | | |
| Requests in the run | 1,872 | | | 3,694 | | |

Machine: AMD Ryzen 5 7530U (6 cores, 12 threads), 14.8 GB RAM, Windows 11, Python 3.11, Locust running on the same machine (so the server and the load generator shared the CPU). The "All requests" row also includes one start-up request per simulated visitor (the first, cold, call that reads the list of reports), which is where most of the largest values come from. Single run per setting, no warm-up pass; repeat it on your own machine before comparing.

What it found: the first attempt at 50 users stalled requests for 30 seconds and raised `QueuePool limit of size 5 overflow 10 reached`. Handlers declared `async def` made blocking database calls on the event loop, so a request waiting for a pooled connection blocked the very loop that had to finish earlier requests to give connections back. The fix: SQLite uses one connection per session instead of a small pool, PostgreSQL gets a larger pool, and the read-only pages and API endpoints are plain `def` functions that run in the thread pool. The numbers above are from after that change. Details in [docs/walkthroughs/03-performance-and-postgres.md](docs/walkthroughs/03-performance-and-postgres.md).

## Deploy on Render

`render.yaml` is a Render Blueprint for a free Docker web service in the Singapore region with a `/health` check. The container applies Alembic migrations, then starts uvicorn on Render's `PORT`.

1. Create a GitHub token for the API quota: GitHub > Settings > Developer settings > Fine-grained tokens, with **Public repositories (read-only)** access and no extra permissions. ArchLens only reads public data, so the token needs nothing else.
2. In Render, choose **New > Blueprint** and select this repository. Render reads `render.yaml`.
3. When prompted, paste the token as the value of `GITHUB_TOKEN`. It is stored in Render, never in the repository.
4. After the first deploy, put the service URL in the **Live demo** line at the top of this README.

| Variable | Set by | Notes |
| :--- | :--- | :--- |
| `GITHUB_TOKEN` | You, in the Render dashboard (`sync: false`) | Raises the GitHub limit from 60 to 5,000 requests per hour |
| `LOG_LEVEL` | `render.yaml` | `INFO` |
| `FORWARDED_ALLOW_IPS` | `render.yaml` | `*`: trust Render's proxy headers so share links and badge snippets use `https://` |
| `PORT` | Render | Read by the container's start command |

The other settings in [Configuration](#configuration) keep their defaults unless you add them in the dashboard.

Free-tier caveats:
- The service sleeps after 15 minutes without traffic, so the first request after a pause is slow.
- SQLite lives on the container's ephemeral disk, so analysis history resets on every redeploy or restart; the example reports are then loaded again. Use a managed database through `DATABASE_URL` if you need history to persist.
- The per-visitor limit is kept in memory, so it resets on restart, and it trusts the first `X-Forwarded-For` address, which a determined client can forge. The GitHub token's quota and the one-hour reuse window are the backstop.

To run the same image elsewhere:

```bash
docker build -t archlens .
docker run -p 8000:8000 -e GITHUB_TOKEN=your_token archlens
```

## API overview

Interactive documentation: Swagger UI at `/docs`, ReDoc at `/redoc`.

| Method | Endpoint | Returns |
| :--- | :--- | :--- |
| `POST` | `/api/v1/analyze` | Analyzes `{"url": "owner/repo", "repo_type": "library"}`. `201` with a new report, or `200` when a report of the same repository and profile from the last hour is reused |
| `POST` | `/api/v1/analyze/stream` | The same analysis, streaming its progress as newline-delimited JSON (`validate`, `reuse`, `fetch` per GitHub call, `dependencies`, `analyze`, `score`, `save`), then a `done` event with the report's address or an `error` event with the codes below |
| `GET` | `/api/v1/analyses/{id}` | The full report as JSON |
| `GET` | `/api/v1/analyses/{id}/markdown` | The report as Markdown (`text/markdown`), with the fixes and the points they add |
| `GET` | `/api/v1/analyses` | Paginated list, filterable: `?offset=0&limit=20&min_score=80&repo_type=library` |
| `GET` | `/api/v1/health` | API status |
| `GET` | `/badge/{owner}/{repo}.svg` | README badge from stored results only (`?profile=` optional) |
| `GET` | `/health` | Service health check |

Web pages: `/` (analyze), `/analysis/{id}` (report), `/analysis/{id}/report.md` (download), `/repo/{owner}/{repo}` (newest report of a repository), `/compare`, `/history` (`?q=`, `?profile=`, `?sort=newest|oldest|score_high|score_low|name`), `/scoring`, `/about`.

Errors share one JSON shape, `{"error": "...", "error_code": "...", "status_code": 404}`:

| Status | `error_code` | When |
| :--- | :--- | :--- |
| `400` | `INVALID_URL` | The input is not `owner/repo` or a GitHub repository URL |
| `404` | `REPO_NOT_FOUND` | The repository does not exist or is private |
| `404` | `ANALYSIS_NOT_FOUND` | No stored analysis has that ID |
| `422` | `EMPTY_REPOSITORY` | The repository has no commits yet (an unknown `repo_type` is also a `422` request validation error) |
| `429` | `TOO_MANY_ANALYSES` | The client started too many analyses; see the `Retry-After` header |
| `502` | `GITHUB_UNAVAILABLE` | GitHub returned an unexpected error or could not be reached |
| `503` | `RATE_LIMIT_EXCEEDED` | The server's GitHub API quota is used up |

## Project structure

```text
ArchLens/
├── main.py                     # FastAPI app: routers, error handlers, startup and shutdown
├── app/
│   ├── cli.py                  # `archlens analyze` command (Typer + Rich)
│   ├── config.py               # Settings from environment variables, project links
│   ├── dependencies.py         # Service singletons and client IP for rate limiting
│   ├── exceptions.py           # One exception class per failure, with status and error code
│   ├── formatting.py           # Number and size formatting for pages and exports
│   ├── templating.py           # Shared Jinja2 environment
│   ├── models/                 # SQLAlchemy models: Repository, RepositoryAlias, Analysis, Metric
│   ├── repositories/           # Database engine and sessions
│   ├── routers/
│   │   ├── web.py              # HTML pages: analyze, report, compare, history, scoring, about
│   │   ├── api.py              # REST API v1, including the progress stream
│   │   └── badge.py            # README badge (stored results only)
│   ├── schemas/                # Pydantic request and response models
│   ├── services/
│   │   ├── analysis_service.py # The pipeline: validate, reuse, rate-limit, fetch, scan dependencies, score, store; reports progress
│   │   ├── dependency_service.py # Dependency files, OSV.dev vulnerability check
│   │   ├── github_service.py   # Async GitHub REST client with retries
│   │   ├── metrics_service.py  # Scoring rules (constants) and the scorer
│   │   ├── scoring_guide.py    # Builds the /scoring page from those constants
│   │   ├── evidence.py         # Check-by-check evidence and the fix plan for a stored report
│   │   ├── charts.py           # Radar chart geometry and language colours
│   │   ├── report_view.py      # Display-ready report and comparison summary
│   │   ├── report_export.py    # Markdown export
│   │   ├── badge_service.py    # SVG badge rendering
│   │   ├── repository_service.py, rate_limiter.py, seed_service.py
│   ├── seed/examples.json      # Example reports loaded into an empty database
│   ├── templates/              # Jinja2 pages and shared macros (_ui.html: icons, gauge, radar)
│   └── static/                 # CSS, one JavaScript file, favicon
├── action.yml                  # Composite GitHub Action
├── alembic/                    # Database migrations
├── docs/
│   ├── process-flows.md        # Every user and system flow, with diagrams
│   ├── roadmap.md              # What was built next, and what was left out
│   ├── sdlc.md                 # How it was planned, designed, built, tested and shipped
│   ├── uat.md                  # User acceptance test: tasks, pass criteria, results
│   ├── walkthroughs/           # One write-up per feature
│   └── screenshots/            # Images used in this README
├── scripts/                    # Example-report builder and seeding helpers
├── tests/
│   ├── unit/                   # Scorer, scoring guide, evidence, charts, badge, export, GitHub client, rate limiter
│   ├── integration/            # Every page, API endpoint and user flow, including the progress stream, GitHub mocked
│   └── load/                   # Locust load test and its seeding script
├── docker-compose.yml          # Local PostgreSQL
├── Dockerfile                  # Multi-stage image, non-root user, health check
└── render.yaml                 # Render Blueprint
```

## Limitations

- **Metadata and dependency files only.** ArchLens reads repository statistics, the root file listing and the dependency files in the root. It does not read source files, run tests or measure coverage.
- **Heuristics, not ground truth.** A file earns points by existing, whatever its quality, and stars are a weak proxy for health. Read a low score as a list of things to look at, not a verdict.
- **Capped counts.** Contributors and recent commits come from one page of GitHub results, so they stop at 100 and show as "100+".
- **Single instance.** The rate limiter lives in memory and resets on restart.
- **Renames are learned.** An old repository name finds the new name's reports only after it has been analyzed once under the old name.
- **Ephemeral demo storage.** On the free host, reports other than the bundled examples (and the badges that point at them) disappear when the service restarts, until someone analyzes the repository again.

## Author

Built by Chandana Vishnu Jayanth · [Portfolio](https://vishnuatgit.github.io) · [Case study](https://vishnuatgit.github.io/projects/archlens.html) ([PDF](https://vishnuatgit.github.io/pdf/archlens-case-study.pdf))

## License

[MIT](LICENSE) © 2026 Chandana Vishnu Jayanth
