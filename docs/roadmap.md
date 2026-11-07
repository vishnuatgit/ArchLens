# ArchLens roadmap (November 2026)

Goal: turn ArchLens from a one-shot repository scorer into a developer productivity tool that runs on every pull
request, tracks a repository's health over time, checks dependencies for known vulnerabilities, and covers a whole
organisation. Every feature ships as its own pull request with a walkthrough in `docs/walkthroughs/` (what it does,
how it works, the design choices and their trade-offs, and the questions an interviewer is likely to ask).

Constraints: free tiers only. SQLite and an in-memory cache stay the defaults, so the Render demo keeps working;
PostgreSQL and Redis are used when `DATABASE_URL` / `REDIS_URL` are set (Docker Compose locally, Neon and Upstash
free tiers online). AI suggestions run only when a model key is set, and fall back to the rule-based suggestions.
Every number published in the README is measured, with the method stated.

## Order and why

| # | Pull request | Builds on | Notes |
|---|---|---|---|
| 1 | Health history and trend charts | the `analyses` table (already one row per run) | Score and the seven dimensions over time for one repository; deltas between runs. Needed by the PR check (base vs head). |
| 2 | Analyse a branch or commit (`ref`) | `github_service` | Contents, commits and workflows read at a given ref. Needed by PR checks. |
| 3 | GitHub Actions integration | 2 | A reusable composite action (`action.yml`) that runs the ArchLens CLI on a repository and ref, writes a job summary and outputs the score. |
| 4 | Pull request quality checks | 1, 3 | The action compares the PR head with its base, posts or updates one PR comment (score change, what got better or worse, the fixes), and fails below a threshold you set. |
| 5 | Dependency graph analysis | contents API | Reads `requirements*.txt`, `pyproject.toml`, `package.json` and lockfiles, `go.mod`; direct dependencies with versions, pinned or not, per ecosystem; shown in the report and the API. |
| 6 | Vulnerability scanning | 5 | Pinned versions checked against the OSV.dev batch API (free, no key); advisories with severity and links; unpinned dependencies listed as "can't check". A separate section, so past scores stay comparable. |
| 7 | Organisation dashboard | 1, 5, 6 | Lists an organisation's public repositories and analyses the top N with streamed progress; one table with scores, grades, vulnerabilities and trends. Needs a GitHub token for more than a few repositories (rate limits). |
| 8 | PostgreSQL and Redis | all | `DATABASE_URL` and `REDIS_URL`; Alembic migrations checked on PostgreSQL; Redis for the report cache and the rate limiter, in-memory fallback; `docker-compose.yml`; CI runs the tests on both databases. |
| 9 | AI improvement suggestions with evidence | 5, 6 | A model proposes fixes from the findings and the files read; every suggestion must cite a file (and line where possible) that ArchLens actually fetched, and uncited ones are dropped. Off without a key. |
| 10 | Integration and load tests | 8 | End-to-end tests against PostgreSQL and Redis in CI; a Locust load test with published p50/p95 latency and throughput for cached and uncached reports. |

Your version of the list put GitHub Actions first. The order above keeps it near the front but adds the two small
pieces it depends on (history, and analysing a ref) first, so each PR works on its own.
