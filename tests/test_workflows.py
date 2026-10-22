"""GitHub Actions workflow files parse and keep their triggers (2026-10-22: an unquoted ': ' in a step name
made pipeline-daily invalid, which GitHub reports only when the workflow is due to run)."""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses(path):
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = wf[True]  # YAML 1.1 reads the key `on` as True
    assert wf["jobs"] and triggers
    for job in wf["jobs"].values():
        assert all(("run" in s) or ("uses" in s) for s in job["steps"])


def test_pipeline_workflows_can_be_started_by_hand():
    for name in ("pipeline-hourly.yml", "pipeline-daily.yml"):
        wf = yaml.safe_load((WORKFLOWS[0].parent / name).read_text(encoding="utf-8"))
        assert "workflow_dispatch" in wf[True] and "schedule" in wf[True]
