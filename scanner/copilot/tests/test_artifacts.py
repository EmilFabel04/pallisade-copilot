import pytest
from scanner.copilot.artifacts import ToolArtifactResult, generate_artifact_id, WRITE_TOOLS


def test_tool_artifact_result_to_dict():
    result = ToolArtifactResult(
        artifact_type="watch_preview",
        action="create",
        data={"name": "Orders Freshness", "watchType": "pipeline_health", "anchorFqn": "analytics.public.orders"},
        editable_fields=["schedule", "monitors"],
        confirmation_tier="inline",
        tool_name="create_watch",
    )
    d = result.to_dict()
    assert d["artifact_id"].startswith("art_")
    assert d["type"] == "watch_preview"
    assert d["action"] == "create"
    assert d["status"] == "proposed"
    assert d["confirmation_tier"] == "inline"
    assert d["editable_fields"] == ["schedule", "monitors"]
    assert d["data"]["name"] == "Orders Freshness"
    assert "tool_name" in d  # Must include tool_name for confirmation routing


def test_tool_artifact_result_synthetic_text():
    result = ToolArtifactResult(
        artifact_type="watch_preview",
        action="create",
        data={},
        editable_fields=[],
        confirmation_tier="inline",
    )
    text = result.to_synthetic_tool_result()
    assert "watch_preview" in text
    assert "create" in text
    assert "Awaiting user confirmation" in text


def test_generate_artifact_id():
    aid = generate_artifact_id()
    assert aid.startswith("art_")
    assert len(aid) > 8


def test_write_tools_set():
    assert "create_watch" in WRITE_TOOLS
    assert "run_watch" not in WRITE_TOOLS  # run_watch is tier "none"
    assert "get_upstream" not in WRITE_TOOLS
