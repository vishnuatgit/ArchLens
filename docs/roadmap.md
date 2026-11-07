# ArchLens roadmap (November 2026)

This page records what was decided, and why, so the reasoning is not lost.

Constraints that shaped every decision: free tiers only; SQLite and an in-memory cache stay the defaults so the
Render demo keeps working with no new services or required environment variables; every number published in the
README is measured, with the method stated; every feature ships as its own pull request with a walkthrough in
`docs/walkthroughs/`.

## Decision: build three features

| # | Feature | Why it earns its place |
|---|---|---|
| 1 | **Dependency and vulnerability scanning** | The score says whether a repository is well kept; it says nothing about the libraries it ships. Reading the manifests and asking OSV.dev (free, no key) answers "is anything here known to be vulnerable, and what do I upgrade to?". It is the one signal people act on immediately. |
| 2 | **GitHub Action health gate** | A score on a web page is read once. A composite Action puts it where the work happens: a job summary, outputs, a failing check below a threshold and one pull-request comment. It reuses the CLI, so it adds little code. |
| 3 | **Measured performance and Postgres-ready CI** | Claims need evidence. A Locust load test gives real latency numbers for the pages visitors open, and a CI job that runs the suite on PostgreSQL proves `DATABASE_URL` is not SQLite-only, without making Postgres required. |

## Considered and not built

| Idea | Decision | Reason |
|---|---|---|
| Health history and trend charts | Already exists | Every analysis is stored, the report page has a score history for the repository, and `/compare` lines two repositories up. Nothing left to build. |
| Per-pull-request scoring | Folded into the Action | ArchLens scores repository metadata (files present, activity, community). A pull request barely changes that, so a per-PR score would be almost always the same number: low signal. The Action's optional PR comment shows the repository's current score and top fixes instead. |
| Organisation dashboard | Deferred | Analysing many repositories at once needs many GitHub calls. The free demo has 60 requests an hour without a token, so it would hit the limit at once. Revisit if a token with a higher budget is available. |
| AI improvement suggestions | Deferred | The rule-based fixes already say what to do and what it is worth in points. A model would add little on top, and its output is hard to evaluate honestly. Revisit when there is a way to measure whether suggestions are right. |
| Redis (cache and rate limiter) | Dropped | The demo is one free instance, so the in-memory cache and rate limiter are enough. Redis would add a second service to run and pay for, with no benefit at that size. |

## Order

Status: all three features are built and merged (pull requests 8 to 10).

1. `feat/dependency-vulnerabilities`: manifests, OSV check, report, API, Markdown, CLI. The score formula is
   unchanged so past scores stay comparable.
2. `feat/github-action`: the composite Action and a workflow that runs it on ArchLens itself.
3. `feat/perf-and-postgres`: load test with published numbers; PostgreSQL in CI and Docker Compose.

Each branch builds on the one before it, so the Action can report the vulnerability count and the load test covers
the final pages.
