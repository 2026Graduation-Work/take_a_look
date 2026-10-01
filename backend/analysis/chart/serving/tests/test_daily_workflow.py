import os
import subprocess
from pathlib import Path

import pytest
import yaml


def steps():
    workflow = Path(__file__).parents[5] / ".github/workflows/chart-serving.yml"
    return yaml.safe_load(workflow.read_text())["jobs"]["publish"]["steps"]


@pytest.mark.parametrize("dry_run,expected", [("", "--publish"), ("true", "--dry-run")])
def test_daily_execution_publishes_by_default_and_preserves_manual_dry_run(dry_run, expected):
    step = next(s for s in steps() if s.get("name") == "Collect, archive and publish confirmed daily results")
    script = step["run"].replace('python -m serving.run_daily "${args[@]}"', 'printf "%s\\n" "${args[@]}"')
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True,
                            env={**os.environ, "DRY_RUN": dry_run, "REPLAY": "true", "REQUESTED_AS_OF": "2026-09-30"})
    assert result.stdout.splitlines() == [expected, "--replay", "--as-of", "2026-09-30"]


def test_recorded_preview_cannot_publish_when_dry_run_was_requested():
    script = next(s for s in steps() if s.get("name") == "Validate execution mode")["run"]
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                            env={**os.environ, "PREVIEW": "true", "DRY_RUN": "true",
                                 "DIAGNOSE": "false", "REPLAY": "false", "AS_OF": ""})
    assert result.returncode != 0
