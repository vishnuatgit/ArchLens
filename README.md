# ArchLens

Score the engineering health of any public GitHub repository from 0 to 100, with clear strengths, concerns and next steps.

[![CI](https://github.com/vishnuatgit/ArchLens/actions/workflows/ci.yml/badge.svg)](https://github.com/vishnuatgit/ArchLens/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

ArchLens is a FastAPI web app, REST API and CLI. It reads a repository's metadata through the GitHub REST API (it never clones code), scores it across seven dimensions, and stores every run in SQLite so you can revisit past reports.

---

## Key Features

- **Multi-Dimensional Codebase Scoring**: Calculates an overall engineering health score (0–100) across 7 dimensions:
  - **Documentation**: README architecture overview, LICENSE permissions, CONTRIBUTING guidelines, and dedicated `docs/` directories.
  - **Activity & Velocity**: Commit frequency over 30 days and days since last release/push.
  - **Organization**: Dedicated source folders (`src/`, `app/`), test suites (`tests/`), and environment configuration manifests (`pyproject.toml`, `dockerfile`, `.env`).
  - **Community Engagement**: GitHub stars, forks, and unique active contributor base.
  - **Maintainability & CI/CD**: GitHub Actions workflows (`.github/workflows/`), open issue count, and repository size.
  - **Security**: `.gitignore`, a dependency lockfile, an `.env` template, and a `SECURITY.md` policy.
  - **Code Quality & Tooling**: linter/formatter config, type-checker config, and pre-commit hooks.

- **Personalized Repository Profiles**:
  - **Open Source Library**: Standard strict scoring across all 5 dimensions.
  - **Personal Project**: Curved scoring that automatically forgives missing CI/CD workflows, low star/fork counts, and `CONTRIBUTING.md` guides.
  - **Enterprise App**: Strictly evaluates test coverage and CI/CD automation while bypassing public community metrics.

- **Modern Dark Glassmorphic Dashboard**:
  - Built with raw CSS, Plus Jakarta Sans typography, ambient radial glow spheres, and backdrop blur glassmorphism.
  - High-precision SVG circular score gauge with dynamic health tier badges (*Strong Codebase*, *Moderate Health*, *Needs Optimization*).
  - 6-tile frosted metadata strip (Stars, Forks, Open Issues, Contributors, Disk Size, Languages).
  - Multi-segment language distribution bars and categorised findings (Key Strengths, Areas of Concern, Actionable Recommendations).

- **Live Asynchronous GitHub Integration**: Async HTTP client (`httpx`) using `asyncio.gather()` to concurrently fetch live repository data, contents, workflows, languages, and commit history.
- **SQLite + Alembic Migration Engine**: Persistent storage for all historical analyses with versioned database migrations and dependency injection.
- **Tested**: unit and integration tests with Pytest and FastAPI's TestClient; GitHub API calls are mocked, so tests need no network.
- **Containerized**: multi-stage Docker build on `python:3.11-slim`, running as a non-root user with a health check.
- **CLI**: `archlens analyze <url> --profile personal` prints the same report in the terminal.

---

## Architecture Diagram

```mermaid
graph TD
    Client["Client Browser / HTTP"]

    subgraph Application Layer
        MW["Middleware (Logging & Latency)"]
        Router["Web Routers (app/routers/web.py)"]
        DI["Dependency Injection (app/dependencies.py)"]
    end

    subgraph Business Logic Layer
        AS["AnalysisService (app/services/analysis_service.py)"]
        MS["MetricsService (app/services/metrics_service.py)"]
        GHS["GitHubService (app/services/github_service.py)"]
        RS["RepositoryService (app/services/repository_service.py)"]
    end

    subgraph Data & External Services
        GHAPI["GitHub REST API v3"]
        DB[("SQLite Database")]
        Alembic["Alembic Migration Engine"]
    end

    Client --> MW
    MW --> Router
    Router --> DI
    DI --> AS
    AS -->|Async Parallel Fetch| GHS
    GHS -->|HTTP Requests| GHAPI
    AS -->|Compute Health Score| MS
    AS -->|Persist Results| RS
    RS -->|SQLAlchemy ORM| DB
    Alembic -->|Schema Versioning| DB
```

---

## Data Schemas & Entity Relationship Diagram

```mermaid
erDiagram
    REPOSITORIES ||--o{ ANALYSES : "has many"
    ANALYSES ||--|| METRICS : "has one"

    REPOSITORIES {
        int id PK
        string owner
        string name
        string url UK
        datetime created_at
    }

    ANALYSES {
        int id PK
        int repository_id FK
        int score
        float duration
        string repo_type
        datetime created_at
    }

    METRICS {
        int id PK
        int analysis_id FK
        int stars
        int forks
        int open_issues
        int language_count
        int contributor_count
        int repo_size
        datetime last_pushed
        string languages_json
        string score_breakdown_json
        string strengths_json
        string weaknesses_json
        string suggestions_json
    }
```

---

## Project Structure

```text
ArchLens/
├── main.py                 # FastAPI application entry point
├── pyproject.toml          # PEP 621 project configuration & tool settings
├── app/
│   ├── config.py               # Environment configuration settings
│   ├── dependencies.py         # FastAPI dependency injection providers
│   ├── exceptions.py           # Custom application exception hierarchy
│   ├── models/                 # SQLAlchemy database models (Repository, Analysis, Metric)
│   ├── repositories/           # DB session management & DAO queries
│   ├── routers/                # FastAPI web routes (/, /analyze, /analysis/{id}, /history, /health)
│   ├── schemas/                # Pydantic validation schemas
│   ├── services/               # GitHub API client, scoring engine & analysis orchestrator
│   ├── templates/              # Jinja2 HTML templates (base, home, results, history, 404)
│   └── static/                 # Glassmorphic CSS design system & assets
├── alembic/                    # Database migration scripts
├── scripts/
│   └── seed.py                 # Script to seed live repository analysis data
├── tests/                      # Pytest unit & integration test suites
│   ├── unit/                   # Unit tests for services and parsers
│   └── integration/            # Integration tests for web routes and DB
├── Dockerfile                  # Multi-stage production container build
├── alembic.ini                 # Alembic migration configuration
├── requirements.txt            # Python dependencies
└── README.md                   # Project documentation
```

---

## Quick Start Guide

### Prerequisites
- **Python 3.11+**
- **Git**

### 1. Clone the Repository
```bash
git clone https://github.com/vishnuatgit/ArchLens.git
cd ArchLens
```

### 2. Create & Activate Virtual Environment
```bash
# On Linux/macOS
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell)
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Database Migrations
Initialize the SQLite database schema using Alembic:
```bash
alembic upgrade head
```

### 5. (Optional) Configure GitHub Personal Access Token
Setting a GitHub Token increases your GitHub API rate limit from 60 to 5,000 requests per hour:
```bash
# On Linux/macOS
export GITHUB_TOKEN="your_personal_access_token"

# On Windows (PowerShell)
$env:GITHUB_TOKEN="your_personal_access_token"
```

### 6. Launch the FastAPI Development Server
```bash
uvicorn main:app --reload
```
Open your browser and navigate to **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

---

## Seeding Live Data

To pre-populate the database with live analysis runs from popular public repositories (e.g. `octocat/Hello-World`, `fastapi/fastapi`, `pallets/flask`):

```bash
python scripts/seed.py
```

---

## API Reference

### Web Dashboard Routes

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Home page with URL input form, profile selector, and recent scans |
| `POST` | `/analyze` | Form submission endpoint to trigger full repository analysis |
| `GET` | `/analysis/{id}` | Detailed engineering report dashboard for a specific scan ID |
| `GET` | `/history` | Paginated analysis history page |
| `GET` | `/health` | System health check endpoint returning API status |

### REST API v1 JSON Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/analyze` | Triggers asynchronous analysis from JSON body (`{"url": "...", "repo_type": "library"}`) |
| `GET` | `/api/v1/analyses/{id}` | Fetches full structured JSON analysis report, health grade, and breakdown |
| `GET` | `/api/v1/analyses` | Paginated query list with filtering (`?offset=0&limit=20&min_score=80&repo_type=library`) |
| `GET` | `/api/v1/health` | REST API operational status health check |

> **Interactive API Documentation**: Access Swagger UI at `http://127.0.0.1:8000/docs` and ReDoc at `http://127.0.0.1:8000/redoc`.

---

## Running Tests

ArchLens maintains a robust test suite covering services, web routes, and database operations.

Run all tests with Pytest:
```bash
pip install -r requirements.txt
pytest --cov=app tests/
```

---

## Docker Deployment

To build and run the multi-stage production Docker container:

```bash
# 1. Build Docker Image
docker build -t archlens:latest .

# 2. Run Container
docker run -d -p 8000:8000 --name archlens-app archlens:latest
```

Access the containerized app at `http://localhost:8000`. The container applies Alembic migrations on start-up, and honours a `PORT` environment variable. Pass `-e GITHUB_TOKEN=...` to raise the GitHub rate limit.

---

## Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./ArchLens.db` | SQLAlchemy database URL |
| `GITHUB_TOKEN` | unset | Optional GitHub token; raises the API limit from 60 to 5,000 requests per hour |
| `LOG_LEVEL` | `INFO` | Python logging level |

Copy `.env.example` to `.env` to set these locally.

---

## Deployment (Render)

`render.yaml` is a Render Blueprint for a free Docker web service with a `/health` check. In Render, choose **New > Blueprint**, point it at this repository, and set `GITHUB_TOKEN` when prompted (optional).

Free-tier caveats:
- The service sleeps after inactivity, so the first request after a pause is slow.
- SQLite lives on the container's ephemeral disk, so analysis history resets on every redeploy or restart. Use a managed database through `DATABASE_URL` if you need it to persist.

---

## Limitations

- Scores are heuristics based on repository metadata and the root directory listing; ArchLens does not read or execute source code.
- Unauthenticated use is limited to 60 GitHub API requests per hour (each analysis makes about six).
- Contributor and recent-commit counts come from the first page of results (up to 100).

---

## License

MIT. See [LICENSE](LICENSE).
