"""The executor should auto-emit an Artifact when a tool with artifact_spec succeeds."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.copilot.tools.base import Tool, ToolCategory, RiskLevel, ToolResult
from scanner.copilot.artifacts.models import ArtifactSpec


@pytest.mark.asyncio
async def test_auto_emit_fires_when_tool_has_artifact_spec_and_succeeds():
    from scanner.copilot.tool_executor import ToolExecutor

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_1"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_1"

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="fake_write_tool",
        description="x",
        category=ToolCategory.CHANGE_PLAN,
        artifact_spec=ArtifactSpec(
            kind="MONITOR",
            status_on_success="applied",
        ),
    )

    async def fake_handler(args):
        return ToolResult(
            success=True,
            data={
                "title": "Test monitor",
                "summary": "freshness 6h",
                "external_ref": {"monitor_id": "m_99"},
                "payload": {"kind": "MONITOR", "monitorId": "m_99", "monitorKind": "FRESHNESS"},
            },
        )

    executor._execute_fake_write_tool = fake_handler  # type: ignore

    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = {"id": "art_77"}
        RepoCls.return_value = repo_instance

        result = await executor._execute_tool(tool, {"__tool_call_id": "tc_1"})

    assert result.success is True
    repo_instance.upsert.assert_awaited_once()
    kwargs = repo_instance.upsert.await_args.kwargs
    assert kwargs["idempotency_key"] == "tc_1:MONITOR"
    assert kwargs["external_ref"] == {"monitor_id": "m_99"}


@pytest.mark.asyncio
async def test_auto_emit_skipped_when_tool_has_no_artifact_spec():
    from scanner.copilot.tool_executor import ToolExecutor

    ctx = MagicMock()
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="read_only",
        description="x",
        category=ToolCategory.LINEAGE,
    )

    async def fake_handler(args):
        return ToolResult(success=True, data={"x": 1})

    executor._execute_read_only = fake_handler  # type: ignore

    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        result = await executor._execute_tool(tool, {})
        RepoCls.assert_not_called()
    assert result.success is True
