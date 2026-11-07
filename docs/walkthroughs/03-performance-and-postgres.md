# Walkthrough 3: measured performance and PostgreSQL-ready CI

## What it does and why it matters

Two claims a project often makes without proof: "it is fast enough" and "it works with PostgreSQL". This feature
replaces both with evidence.

1. **A load test** (Locust, `tests/load/`) that hits only pages and endpoints answered from stored reports, so
   GitHub is never called. The README publishes the measured p50 and p95 latency, the maximum and the requests per
   second, with the exact method and the machine it ran on.
2. **PostgreSQL support you can check.** `DATABASE_URL` accepts a PostgreSQL URL, a CI job runs the migrations and the
   whole test suite on a PostgreSQL 16 service container, and `docker-compose.yml` starts one locally. SQLite is
   still the default; nothing requires PostgreSQL.

Doing both found two real problems, which are fixed:

- **Under load the app stalled.** At 50 visitors some requests waited 30 seconds and failed with
  `QueuePool limit of size 5 overflow 10 reached`.
- **A SQLite-only assumption.** An analysis id larger than 2^31 returned a server error on PostgreSQL (its integer
  columns are 32 bits) instead of "not found".

## How it works end to end

```
tests/load/seed_reports.py    fills a database with 60 repositories x 3 reports (no GitHub)
tests/load/locustfile.py      simulated visitors: report page, history, API list/detail, badge, permalink,
                              Markdown export, stored comparison; every response must be 200
README "Performance"          the method, the commands, the table of results

app/config.py                 normalize_database_url(): postgres:// and postgresql:// -> postgresql+psycopg://
app/repositories/db.py        pool settings per database (SQLite: no pool; PostgreSQL: a sized pool)
tests/db.py                   TEST_DATABASE_URL: run the database tests on any database
.github/workflows/ci.yml      job test-postgres: service container, alembic up/down/up, pytest
docker-compose.yml            local PostgreSQL 16
pyproject.toml                optional extra "postgres" = psycopg[binary]; Locust is a dev dependency
```

**The load test.** Each simulated visitor first reads the list of reports (as a person would from the history
page), then loops over weighted actions with 0.2 to 1 second of think time. A response that is not HTTP 200 is
counted as a failure. The server is started with the same command as `render.yaml`. Latency numbers come from
Locust's own CSV output.

**What the load test found.** The route handlers were declared `async def` but called the database synchronously.
That blocks the event loop while a query runs. SQLAlchemy's default pool for a SQLite file holds 5 connections
(plus 10 extra). A request keeps its connection until its session is closed after the response is sent, and that
closing needs the event loop. When many requests were in flight, the pool ran dry, a handler blocked the loop
waiting for a connection, and the requests that would have released connections could not finish: a stall until the
30 second pool timeout, then an error. The fix has three parts:

1. SQLite: no pool (`NullPool`). Opening a local file is cheap, so every session gets its own connection and
   cannot run out.
2. PostgreSQL: a real pool of 20 (+20 overflow) with `pool_pre_ping`, and a 15 second timeout.
3. Read-only pages and endpoints changed from `async def` to `def`. FastAPI runs a `def` handler in a thread pool,
   so waiting for the database no longer blocks the event loop. Handlers that `await` (starting an analysis, the
   compare page) stay `async`.

After the change, the same test at 50 visitors had no failures and a maximum of about 2.5 seconds.

**PostgreSQL.** Hosts hand out `postgres://` or `postgresql://` URLs. SQLAlchemy would read the second as the old
psycopg2 driver and reject the first, so `normalize_database_url` rewrites both to `postgresql+psycopg://` (the
psycopg 3 driver). The tests choose their database from `TEST_DATABASE_URL` through one helper (`tests/db.py`), so
the same code runs on SQLite by default and PostgreSQL in CI. The CI job also applies the migrations, rolls them
back to nothing and applies them again, which proves the Alembic history works on PostgreSQL, not just SQLite.

## Design choices and trade-offs

| Choice | Why | Cost |
|---|---|---|
| Locust, as a dev dependency only | Scenarios are plain Python; reports p50/p95 and requests per second | The load generator ran on the same machine as the server, so the numbers are conservative and noisy |
| Load test only on stored-report endpoints | No GitHub calls, no rate limit, repeatable | Says nothing about the speed of a new analysis (which is dominated by GitHub's latency) |
| Seed the database directly | Fast and deterministic (fixed random seed) | The data is synthetic copies of the example reports |
| `NullPool` for SQLite | Removes the pool as a failure mode; a file open is microseconds | Not suitable for an in-memory database (handled: in-memory URLs keep one shared connection) |
| `def` handlers for reads | The thread pool absorbs waiting; the event loop stays free | Thread pool size (40) is the new concurrency limit; very high load needs more instances |
| Keep SQLite as the default | The free demo needs no extra service | Persistent history still needs a managed PostgreSQL |
| `psycopg` as an optional extra | Nobody is forced to install it | One more install step for PostgreSQL users |
| CI job on a service container | Same database engine as production would use | A few minutes of extra CI time |
| Tests create tables with `create_all`; a separate CI step runs Alembic | Fast tests and a real migration check | The two are different code paths, so both are exercised |

## Limits

- The numbers are one run per setting on one laptop (AMD Ryzen 5 7530U, 14.8 GB, Windows 11) with Locust sharing the
  CPU. Render's free instance is slower. They show behaviour under concurrency, not a capacity guarantee.
- No warm-up pass, so the first requests (cold caches, first template render) are included.
- Only reads are load tested. Starting analyses is limited by design (5 per visitor per 10 minutes) and by GitHub.
- PostgreSQL was verified on PostgreSQL 16.2 locally and is configured to run on a 16 service container in CI. Docker
  was not available on the development machine, so `docker-compose.yml` itself was not run.
- Report data is not migrated between SQLite and PostgreSQL; a new database starts empty and loads the examples.

## Likely interview questions

1. **What did the load test find, and how did you fix it?** Requests stalled for 30 seconds at 50 users with a
   `QueuePool` timeout. Blocking database calls inside `async def` handlers held the event loop, so connections could
   not be returned. I removed the pool for SQLite, sized one for PostgreSQL and made read-only handlers plain
   `def` so they run in the thread pool. Then I re-ran the same test: no failures.
2. **Why is a `def` handler better here than `async def`?** The database driver is synchronous. In an `async def`
   handler a slow query blocks every other request on the loop. In a `def` handler FastAPI runs it in a thread
   pool, so the loop keeps serving. `async def` is right only when the handler awaits something.
3. **What do p50 and p95 mean, and why report both?** The median (half the requests were faster) and the 95th
   percentile (95 percent were faster). The median shows the typical experience, p95 shows how bad the slow tail
   is. The maximum is shown as well because one slow outlier is what a user remembers.
4. **Why test only stored reports?** A new analysis calls GitHub, which would measure GitHub and burn the rate
   limit. Stored pages are what most visitors open, and they exercise our code and database.
5. **How do you know it works on PostgreSQL?** CI starts PostgreSQL 16, applies the migrations, rolls them back and
   applies them again, then runs the whole test suite with `TEST_DATABASE_URL` pointing at it. Running it also found
   a bug: an id above the 32-bit range raised a database error on PostgreSQL.
6. **Why rewrite `postgres://` to `postgresql+psycopg://`?** SQLAlchemy needs the dialect and driver in the URL.
   Hosting providers give `postgres://` or `postgresql://`. The rewrite makes them work and uses psycopg 3, the
   maintained driver.
7. **How do you keep SQLite as the default without breaking PostgreSQL?** Nothing in the app imports a PostgreSQL
   driver unless the URL asks for it. The driver is an optional extra. Queries use portable SQLAlchemy constructs
   (`func.lower`, `contains`), and the CI job proves they run on both.
8. **Why do the numbers need caveats?** One machine, Locust sharing the CPU, one run, no warm-up, synthetic data.
   They are real measurements of this code on this machine, useful to compare before and after a change, but not
   a promise about another host.
