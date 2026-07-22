# ArchLens

ArchLens is a scalable FastAPI application that analyzes GitHub repositories and generates engineering health and quality scores based on documentation, community, activity, and organization metrics.

## Features

- **Automated Codebase Analysis**: Computes a health score (0-100) based on 5 core dimensions:
  - Documentation (README, LICENSE, CONTRIBUTING)
  - Activity (Recent commits, age of repository)
  - Organization (Source layout, test suites, configs)
  - Community (Stars, forks, active contributors)
  - Maintainability (Open issues ratio, CI/CD presence, repository size)
- **Live GitHub Integration**: Leverages the GitHub REST API to perform live repository scans.
- **SQLite Database**: Persists scans and logs history using SQLAlchemy and Alembic.
- **Beautiful Dashboard**: Glassmorphism UI using Jinja2 and raw CSS to visualize scores, breakdowns, and actionable suggestions.
- **Dockerized**: Production-ready multi-stage Docker build.

## Project Structure

```text
ArchLens/
├── main.py                 # FastAPI application entry point
├── app/
│   ├── config.py               # Environment configuration
│   ├── models/                 # SQLAlchemy DB models
│   ├── repositories/           # DB session and migrations
│   ├── routers/                # FastAPI web routes
│   ├── schemas/                # Pydantic validation schemas
│   ├── services/               # GitHub API client and scoring engines
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # CSS and JS assets
├── scripts/
│   └── seed.py                 # Script to seed live data
├── tests/                      # Pytest unit and integration tests
├── Dockerfile                  # Production container definition
├── alembic.ini                 # Alembic configuration
└── requirements.txt            # Python dependencies
```

## Quick Start (Local Setup)

### Prerequisites
- Python 3.11+
- Git

### 1. Clone the Repository
```bash
git clone https://github.com/vishnuatgit/ArchLens.git
cd ArchLens
```

### 2. Set Up Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run Database Migrations
Initialize the SQLite database schema:
```bash
alembic upgrade head
```

### 4. (Optional) Set GitHub Token
To avoid unauthenticated rate limits, set your GitHub Personal Access Token:
```bash
export GITHUB_TOKEN=your_token_here
```

### 5. Start the Server
```bash
uvicorn main:app --reload
```
Navigate to `http://127.0.0.1:8000` to access the ArchLens dashboard.

## Running Tests
ArchLens is fully tested with Pytest. To run the test suite:
```bash
pytest
```

## Docker Deployment

Build and run the ArchLens container locally:

```bash
docker build -t archlens:latest .
docker run -p 8000:8000 archlens:latest
```

## License
MIT License