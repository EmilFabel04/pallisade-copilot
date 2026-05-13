"""Group A change_plan tools must declare ArtifactSpec on registration."""
from copilot.tools.registry import ToolRegistry


def test_create_change_plan_has_pr_change_artifact_spec():
    r = ToolRegistry()
    tool = r._tools["create_change_plan"]
    assert tool.artifact_spec is not None
    assert tool.artifact_spec.kind == "PR_CHANGE"
    assert tool.risk_level is not None


def test_validate_change_plan_has_pr_change_artifact_spec():
    r = ToolRegistry()
    tool = r._tools["validate_change_plan"]
    assert tool.artifact_spec is not None
    assert tool.artifact_spec.kind == "PR_CHANGE"


def test_apply_change_plan_has_pr_change_artifact_spec_and_applied_status():
    r = ToolRegistry()
    tool = r._tools["apply_change_plan"]
    assert tool.artifact_spec is not None
    assert tool.artifact_spec.kind == "PR_CHANGE"
    assert tool.artifact_spec.status_on_success == "applied"
