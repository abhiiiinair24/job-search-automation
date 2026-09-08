"""Validates the GitHub Actions workflow file's structure.

This doesn't run the workflow (that requires actual GitHub Actions
infrastructure) - it parses the YAML and checks the pieces the spec
requires are actually present: both trigger types, minimal permissions,
the DST-safe time guard, and the expected step sequence.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW_PATH_CANDIDATES = [
    # Standard deployed layout: <repo-root>/.github/workflows/job-search.yml,
    # where <repo-root> is the parent of job-search-engine/ (this file
    # lives at job-search-engine/tests/test_github_workflow.py, so that's
    # two levels up from this file's directory).
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "job-search.yml",
    # Fallback: .github kept inside job-search-engine/ itself (non-standard,
    # but tolerated so this test still finds the file if someone structures
    # their repo that way).
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "job-search.yml",
]
WORKFLOW_PATH = next((p for p in WORKFLOW_PATH_CANDIDATES if p.exists()), WORKFLOW_PATH_CANDIDATES[0])


@pytest.fixture(scope="module")
def workflow():
    if not WORKFLOW_PATH.exists():
        pytest.skip(f"Workflow file not found at {WORKFLOW_PATH}")
    with WORKFLOW_PATH.open() as f:
        doc = yaml.safe_load(f)
    return doc


def _triggers(workflow):
    # YAML 1.1 parses the bare key "on" as the boolean True - this is a
    # well-known GitHub Actions/PyYAML quirk. GitHub's own parser handles
    # "on:" correctly regardless; we just need to look under both possible
    # keys here since we're using a strict YAML parser to validate it.
    return workflow.get("on", workflow.get(True))


def test_workflow_file_is_valid_yaml(workflow):
    assert workflow is not None
    assert "jobs" in workflow


def test_workflow_has_schedule_trigger(workflow):
    triggers = _triggers(workflow)
    assert "schedule" in triggers
    assert len(triggers["schedule"]) >= 1


def test_workflow_schedule_covers_both_dst_offsets_for_8am_and_8pm(workflow):
    triggers = _triggers(workflow)
    crons = {entry["cron"] for entry in triggers["schedule"]}
    # 8:00 AM ET -> 12:00 or 13:00 UTC depending on DST.
    assert "0 12 * * *" in crons
    assert "0 13 * * *" in crons
    # 8:00 PM ET -> 00:00 or 01:00 UTC depending on DST.
    assert "0 0 * * *" in crons
    assert "0 1 * * *" in crons


def test_workflow_supports_manual_dispatch(workflow):
    triggers = _triggers(workflow)
    assert "workflow_dispatch" in triggers


def test_workflow_has_minimal_write_permission_only(workflow):
    assert workflow["permissions"] == {"contents": "write"}


def test_workflow_has_concurrency_guard(workflow):
    assert "concurrency" in workflow
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_workflow_uses_python_312(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    setup_python_steps = [s for s in steps if s.get("uses", "").startswith("actions/setup-python")]
    assert len(setup_python_steps) == 1
    assert setup_python_steps[0]["with"]["python-version"] == "3.12"


def test_workflow_checks_out_repository(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    assert any(s.get("uses", "").startswith("actions/checkout") for s in steps)


def test_workflow_has_local_time_guard_step_before_everything_else(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    assert "America/New_York" in steps[0]["run"]
    assert steps[0]["id"] == "time_check"


def test_workflow_gates_later_steps_on_time_check(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    # Every step after the time-check guard itself should be conditioned
    # on it, so off-schedule cron firings genuinely do nothing.
    for step in steps[1:]:
        assert step.get("if") == "steps.time_check.outputs.run == 'true'"


def test_workflow_verifies_secrets_before_running_search(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    names = [s.get("name", "") for s in steps]
    verify_idx = next(i for i, n in enumerate(names) if "secret" in n.lower())
    run_idx = next(i for i, n in enumerate(names) if "run job search" in n.lower())
    assert verify_idx < run_idx


def test_workflow_does_not_hard_code_board_slugs(workflow):
    """GREENHOUSE_BOARDS/LEVER_COMPANIES must not appear as literal values
    anywhere in the workflow - boards live in config/boards.json instead."""
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    for step in steps:
        env = step.get("env", {})
        # It's fine for these keys to be *absent*; it's not fine for them
        # to be set to a literal, non-secret board name.
        for key in ("GREENHOUSE_BOARDS", "LEVER_COMPANIES"):
            if key in env:
                assert "secrets." in env[key], (
                    f"{key} must not be a hard-coded literal in the workflow"
                )


def test_workflow_reads_gmail_credentials_from_secrets_only(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run job search and send email")
    env = run_step["env"]
    for key in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        assert key in env
        assert env[key].startswith("${{ secrets.")


def test_workflow_reads_adzuna_credentials_from_secrets_only(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run job search and send email")
    env = run_step["env"]
    for key in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        assert key in env
        assert env[key].startswith("${{ secrets.")


def test_workflow_checks_adzuna_secrets_are_required(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    verify_step = next(s for s in steps if "secret" in s.get("name", "").lower())
    run_script = verify_step["run"]
    assert "ADZUNA_APP_ID" in run_script
    assert "ADZUNA_APP_KEY" in run_script


def test_workflow_runs_the_orchestrator_not_duplicated_logic(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run job search and send email")
    assert "jobsearch.orchestrator" in run_step["run"]


def test_workflow_commits_seen_state_conditionally(workflow):
    steps = workflow["jobs"]["search-and-notify"]["steps"]
    commit_step = next(s for s in steps if "commit" in s.get("name", "").lower())
    assert "git status --porcelain" in commit_step["run"]
    assert "git push" in commit_step["run"]


def test_workflow_never_echoes_secret_values_directly(workflow):
    """Secrets should only appear as ${{ secrets.X }} references, never
    echoed/printed as bare shell variables."""
    import re

    steps = workflow["jobs"]["search-and-notify"]["steps"]
    secret_names = ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"]
    for step in steps:
        run_script = step.get("run", "")
        for line in run_script.splitlines():
            if "echo" in line.lower():
                for name in secret_names:
                    # Echoing the ${{ secrets.X }} expression form is fine
                    # (GitHub masks it); echoing a bare shell var like
                    # "$GMAIL_CLIENT_ID" or "$name"/"$missing" listing is
                    # what we guard against below in the secrets-check step,
                    # which only ever echoes variable *names*, not values.
                    assert f"${name}" not in line
