"""_emit_for_tool returns the persisted row; the executor stashes a
typed_artefact event on ToolResult.stream_events so the streaming layer
in llm.py can yield it to the client.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.copilot.tool_executor import ToolExecutor
from scanner.copilot.tools.base import Tool, ToolCategory, RiskLevel, ToolResult
from scanner.copilot.artifacts.models import ArtifactSpec


def _make_executor() -> ToolExecutor:
    ctx = MagicMock()
    ctx.base_url = "http://localhost:3000"
    ctx.org_id = "org_1"
    ctx.user_id = "user_1"
    ctx.session_id = "sess_1"
    ctx.agent_run_id = "run_1"
    ctx._active_agent_session_id = None
    ex = ToolExecutor.__new__(ToolExecutor)
    ex.context = ctx
    return ex


def _make_monitor_tool() -> Tool:
    return Tool(
        name="create_monitor",
        description="Create a single MONITOR artefact.",
        category=ToolCategory.OBSERVABILITY,
        risk_level=RiskLevel.LOW,
        artifact_spec=ArtifactSpec(kind="MONITOR", status_on_success="applied"),
    )


@pytest.mark.asyncio
async def test_emit_for_tool_returns_persisted_row():
    """The auto-emit helper must surface the upserted dict back to the caller."""
    ex = _make_executor()
    tool = _make_monitor_tool()
    tool_result = ToolResult(
        success=True,
        data={
            "title": "Freshness monitor",
            "summary": "6h on analytics.orders",
            "payload": {
                "kind": "MONITOR",
                "monitorId": "mon_1",
                "monitorKind": "FRESHNESS",
                "targetFqn": "analytics.public.orders",
            },
            "external_ref": {"monitor_id": "mon_1"},
        },
    )
    persisted = {
        "id": "art_42",
        "kind": "MONITOR",
        "status": "applied",
        "title": "Freshness monitor",
        "summary": "6h on analytics.orders",
        "payload": tool_result.data["payload"],
        "externalRef": {"monitor_id": "mon_1"},
        "riskLevel": "LOW",
        "agentSessionId": None,
        "sourceSessionId": "sess_1",
        "isPinned": False,
        "isSaved": False,
    }
    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = persisted
        RepoCls.return_value = repo_instance
        out = await ex._emit_for_tool(tool, {}, tool_result)

    assert out is not None
    assert out["id"] == "art_42"


@pytest.mark.asyncio
async def test_emit_for_tool_returns_none_when_no_spec():
    ex = _make_executor()
    tool = Tool(
        name="read_only",
        description="x",
        category=ToolCategory.LINEAGE,
    )
    out = await ex._emit_for_tool(tool, {}, ToolResult(success=True, data={}))
    assert out is None


def test_build_typed_artefact_event_shape():
    ex = _make_executor()
    persisted = {
        "id": "art_42",
        "kind": "MONITOR",
        "status": "applied",
        "title": "Freshness monitor",
        "summary": "6h on analytics.orders",
        "payload": {"kind": "MONITOR", "monitorId": "mon_1", "monitorKind": "FRESHNESS"},
        "externalRef": {"monitor_id": "mon_1"},
        "riskLevel": "LOW",
        "agentSessionId": None,
        "sourceSessionId": "sess_1",
        "isPinned": False,
        "isSaved": False,
    }
    event = ex._build_typed_artefact_event(persisted, tool_name="create_monitor")

    assert event["type"] == "typed_artefact"
    assert event["artefactId"] == "art_42"
    assert event["kind"] == "MONITOR"
    assert event["status"] == "applied"
    assert event["title"] == "Freshness monitor"
    assert event["payload"]["monitorId"] == "mon_1"
    assert event["externalRef"] == {"monitor_id": "mon_1"}
    assert event["riskLevel"] == "LOW"
    assert event["toolName"] == "create_monitor"
    assert event["isPinned"] is False
    assert event["isSaved"] is False


@pytest.mark.asyncio
async def test_execute_tool_stashes_typed_artefact_event_on_result():
    """_execute_tool must append a typed_artefact event to ToolResult.stream_events
    after a successful auto-emit so the llm.py streaming layer can yield it."""
    ex = _make_executor()
    tool = _make_monitor_tool()

    async def fake_handler(args):
        return ToolResult(
            success=True,
            data={
                "title": "Freshness monitor",
                "summary": "6h on analytics.orders",
                "payload": {
                    "kind": "MONITOR",
                    "monitorId": "mon_1",
                    "monitorKind": "FRESHNESS",
                    "targetFqn": "analytics.public.orders",
                },
                "external_ref": {"monitor_id": "mon_1"},
            },
        )

    ex._execute_create_monitor = fake_handler  # type: ignore[attr-defined]

    persisted = {
        "id": "art_42",
        "kind": "MONITOR",
        "status": "applied",
        "title": "Freshness monitor",
        "summary": "6h on analytics.orders",
        "payload": {"kind": "MONITOR", "monitorId": "mon_1", "monitorKind": "FRESHNESS"},
        "externalRef": {"monitor_id": "mon_1"},
        "riskLevel": "LOW",
        "agentSessionId": None,
        "sourceSessionId": "sess_1",
        "isPinned": False,
        "isSaved": False,
    }
    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = persisted
        RepoCls.return_value = repo_instance
        result = await ex._execute_tool(tool, {"__tool_call_id": "tc_1"})

    assert result.success is True
    assert len(result.stream_events) == 1
    ev = result.stream_events[0]
    assert ev["type"] == "typed_artefact"
    assert ev["artefactId"] == "art_42"
    assert ev["toolName"] == "create_monitor"
