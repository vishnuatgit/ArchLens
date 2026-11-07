"""Structure checks for action.yml and the workflow that dogfoods it (no GitHub needed)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
WORKFLOW = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "archlens-health.yml").read_text(encoding="utf-8")
)
STEPS = ACTION["runs"]["steps"]


def test_action_is_a_composite_with_the_documented_inputs_and_outputs():
    assert ACTION["runs"]["using"] == "composite"
    assert ACTION["name"] and ACTION["description"]
    assert set(ACTION["inputs"]) == {
        "repository",
        "profile",
        "min-score",
        "comment",
        "github-token",
        "python-version",
    }
    # Sensible defaults: the current repository, the workflow's own token, no gate, no comment
    assert ACTION["inputs"]["repository"]["default"] == "${{ github.repository }}"
    assert ACTION["inputs"]["github-token"]["default"] == "${{ github.token }}"
    assert ACTION["inputs"]["min-score"]["default"] == ""
    assert ACTION["inputs"]["comment"]["default"] == "false"
    assert set(ACTION["outputs"]) == {"score", "grade", "vulnerabilities"}


def test_every_output_points_at_a_step_that_exists_and_sets_it():
    step_ids = {step["id"]: step for step in STEPS if "id" in step}
    for name, output in ACTION["outputs"].items():
        match = re.fullmatch(r"\$\{\{ steps\.(\w+)\.outputs\.([\w-]+) \}\}", output["value"])
        assert match, name
        step_id, key = match.groups()
        assert step_id in step_ids
        assert f"{key}=" in step_ids[step_id]["run"]


def test_every_run_step_names_its_shell():
    for step in STEPS:
        if "run" in step:
            assert step.get("shell") == "bash", step.get("name")


def test_inputs_reach_scripts_through_env_not_string_interpolation():
    # `${{ inputs.x }}` pasted into a script is a command-injection risk; env vars are not
    for step in STEPS:
        assert "${{ inputs." not in step.get("run", ""), step.get("name")


def test_actions_used_are_pinned_to_a_major_version():
    for step in STEPS:
        if "uses" in step:
            assert re.search(r"@v\d+$", step["uses"]), step["uses"]


def test_comment_step_only_runs_when_asked_on_pull_requests_and_cannot_fail_the_job():
    (step,) = [s for s in STEPS if s.get("uses", "").startswith("actions/github-script")]
    assert "inputs.comment == 'true'" in step["if"]
    assert "github.event_name == 'pull_request'" in step["if"]
    assert step["continue-on-error"] is True
    # It updates the one comment it created before, found by a hidden marker
    assert "archlens-health-comment" in step["with"]["script"]
    assert "updateComment" in step["with"]["script"] and "createComment" in step["with"]["script"]


def test_gate_step_fails_the_job_only_for_the_below_minimum_exit_code():
    (step,) = [s for s in STEPS if s.get("name") == "Enforce the minimum score"]
    assert step["if"] == "steps.analyze.outputs.exit-code == '2'"
    assert "exit 1" in step["run"]


def test_summary_step_appends_the_markdown_report():
    (step,) = [s for s in STEPS if s.get("name") == "Write job summary"]
    assert "GITHUB_STEP_SUMMARY" in step["run"] and "report.md" in step["run"]


def test_workflow_runs_on_demand_and_weekly_but_not_on_push():
    triggers = WORKFLOW[True] if True in WORKFLOW else WORKFLOW["on"]  # YAML reads `on` as True
    assert set(triggers) == {"workflow_dispatch", "schedule"}
    assert re.fullmatch(r"\S+ \S+ \S+ \S+ \S+", triggers["schedule"][0]["cron"])
    assert WORKFLOW["permissions"] == {"contents": "read"}
    uses = [step.get("uses") for step in WORKFLOW["jobs"]["health"]["steps"]]
    assert "./" in uses  # it dogfoods the action in this repository
