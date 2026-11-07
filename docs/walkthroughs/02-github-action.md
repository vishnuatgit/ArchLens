# Walkthrough 2: the GitHub Action health gate

## What it does and why it matters

A score on a web page is read once and forgotten. The Action puts ArchLens where the team already looks:

- the **job summary** of a workflow run shows the full Markdown report;
- **outputs** (`score`, `grade`, `vulnerabilities`) can feed later steps;
- an optional **`min-score`** fails the job when the repository drops below a number, so health becomes a gate;
- an optional **pull-request comment** (`comment: true`) shows the score, grade, top fixes and the dependency
  summary, and is **updated in place** instead of adding a new comment on every push.

By default it analyzes the repository running the workflow, using the workflow's own `GITHUB_TOKEN`. No secrets
and no ArchLens server are needed: it runs the same CLI you run locally.

Per-pull-request scoring was deliberately not built. ArchLens scores repository metadata (files, activity,
community), which a single pull request barely changes, so a per-PR score would almost always be the same number.
The comment reports the repository's current health and what to fix first.

## How it works end to end

```
workflow step: uses: vishnuatgit/ArchLens@main            action.yml (composite)
  1. actions/setup-python                                  Python 3.11 by default
  2. pip install --editable $GITHUB_ACTION_PATH            installs ArchLens and its dependencies from the repo
  3. "Analyze" (bash)
       alembic upgrade head                                creates a throwaway SQLite database in RUNNER_TEMP
       archlens analyze $REPOSITORY --format json
              --output-dir $RUNNER_TEMP/archlens [--min-score N]
              -> app/cli.py -> AnalysisService.run()       the same pipeline as the web app
              -> writes report.md, result.json, comment.md
       exit 1 -> the analysis failed: fail the step
       exit 2 -> below min-score: remember it, carry on
       read result.json -> outputs score, grade, vulnerabilities
  4. "Write job summary"        cat report.md >> $GITHUB_STEP_SUMMARY
  5. "Post or update comment"   actions/github-script, only if comment == true and the event is pull_request
  6. "Enforce the minimum score" fails the job if step 3 saw exit code 2
```

Files: `action.yml`, `app/cli.py` (`--format`, `--min-score`, `--output-dir`, `write_report_files`),
`app/services/report_export.py` (`report_to_comment`, `report_to_summary`),
`.github/workflows/archlens-health.yml` (the Action running on ArchLens itself on `workflow_dispatch` and a weekly
schedule, not on every push), `tests/unit/test_action.py`, `tests/unit/test_cli.py`.

Details worth knowing:

- **Exit codes** are the contract between the CLI and the Action: `0` fine, `1` the analysis failed (not found, rate
  limit, GitHub down), `2` the score is below `--min-score`. The gate happens in the last step so that the summary
  and the comment are still published when the check fails. That is when people most want to read them.
- **Machine output.** With `--format json` or `markdown` stdout holds only the report; messages go to stderr. The
  `result.json` file has the score, grade, dimension points, top fixes, dependency counts and
  `vulnerability_count`. That count is `null` (an empty output) when OSV could not be reached, so a gate never
  mistakes "unknown" for "zero".
- **One comment, updated.** `comment.md` starts with a hidden marker (`<!-- archlens-health-comment -->`). The
  script lists the pull request's comments, finds the one with the marker and updates it, or creates it.
- **Safe inputs.** Inputs reach the shell through `env:`, never pasted into the script text with `${{ }}`. A
  pull-request title or repository name containing shell syntax therefore cannot run as code. A test enforces it.
- **Forks.** Pull requests from forks get a read-only token and cannot comment. The comment step has
  `continue-on-error: true`, so the job still finishes with the summary and the gate.
- **Database.** The CLI stores reports in a SQLite file; in the Action that file lives in a temporary folder and is
  discarded with the runner.

## Design choices and trade-offs

| Choice | Why | Cost |
|---|---|---|
| Composite action, not Docker or JavaScript | No image to build or host; reuses the CLI; free | Installs Python packages on every run (about 20-30 seconds); needs a Linux runner for the shell steps |
| `pip install --editable` the action path | The project's packaging lists only the top-level `app` package, so a normal install would miss subpackages; an editable install works from the checked-out action | Not a published wheel |
| Gate in a separate last step | Summary and comment are published even when the gate fails | One more step |
| Exit code 2 for "below minimum" | Separates "the tool broke" from "the repository is below the bar" | Callers must know the two codes |
| `github-script` for the comment | Official action, no extra dependency, a few lines of JavaScript | Needs `pull-requests: write` |
| Weekly + manual dogfood workflow | The score reads metadata that rarely changes between commits, so every push would be noise and API quota | A regression can wait up to a week to show |
| Default token | Works with no setup | The workflow token can only read repositories it has access to, which is what you want for "the current one" |

## Limits

- Linux runners (the scripts use bash and POSIX paths).
- The score is about repository metadata, not about the code in the pull request.
- Fork pull requests cannot post the comment.
- Uses `@main` of this repository unless you pin a tag or commit; pin one for reproducible builds.
- GitHub API quota: one analysis costs 7 to 12 requests; the workflow token allows 1,000 per hour per repository.

## Likely interview questions

1. **Why a composite action?** It only needs to install and run a Python CLI. A composite action has no image to
   build and no JavaScript to maintain, and it reuses the code and tests of the CLI.
2. **How does `min-score` fail the job but still publish the report?** The CLI exits with code 2 after writing its
   output. The analyze step records the code and continues; the summary and comment run; a final step fails the
   job. Exit 1 (a real error) fails at once.
3. **How do you avoid duplicate comments?** A hidden HTML marker in the body. The script finds the comment that
   contains it and updates it; only if none exists does it create one.
4. **Is it safe against injection from inputs?** Inputs go through environment variables and the script quotes
   them. Pasting `${{ inputs.x }}` into a script is the classic injection hole, and a unit test fails if anyone
   does it.
5. **What happens on a pull request from a fork?** The token is read-only, so the comment request is denied. That
   step is `continue-on-error`, so you get a warning and the rest of the job (summary, gate) still works.
6. **Why not run it on every push?** The score reads repository metadata that rarely changes between commits, and
   each run spends API quota. A weekly and manual run is enough to catch drift.
7. **How did you test an Action without GitHub?** `action.yml` is parsed in a unit test (composite, inputs and
   defaults, outputs wired to real step ids, shells set, pinned versions, comment guard, gate condition). The CLI
   behaviour is tested with Typer's runner, and an integration test runs the real pipeline with fake GitHub and
   OSV and checks the files the Action publishes. I also ran the Analyze step's script locally against GitHub.
8. **Why did you need `alembic upgrade head` in the Action?** The CLI saves each report to the database like the
   web app does, and a fresh runner has an empty file. Alembic creates the schema the same way as in production.
