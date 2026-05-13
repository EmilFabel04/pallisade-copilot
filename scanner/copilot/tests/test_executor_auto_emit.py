"""The executor should auto-emit an Artifact when a tool with artifact_spec succeeds."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.copilot.tools.base import Tool, ToolCategory, RiskLevel, ToolResult
from scanner.copilot.artifacts.models import ArtifactSpec


@pytest.mark.asyncio
async def test_auto_emit_fires_when_tool_has_artifact_spec_and_succeeds():
    from scanner.copilot.tool_executor import ToolExecutor
    from scanner.copilot.artifacts.models import ArtifactRisk

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_1"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_1"
    # MagicMock would return a Mock for arbitrary attribute lookups; pin to None
    # so getattr(..., "_active_agent_session_id", None) returns None, forcing the
    # fallback (tool_call_id-keyed) idempotency path.
    ctx._active_agent_session_id = None

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="fake_write_tool",
        description="x",
        category=ToolCategory.CHANGE_PLAN,
        risk_level=RiskLevel.LOW,
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
    # Risk level from the Tool definition must be propagated to the artefact row.
    assert kwargs["risk_level"] == ArtifactRisk.LOW


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


@pytest.mark.asyncio
async def test_auto_emit_failure_does_not_break_tool_result():
    """If artefact persistence fails, the tool result should still be returned successfully."""
    from scanner.copilot.tool_executor import ToolExecutor

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_1"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_1"
    ctx._active_agent_session_id = None

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="flaky_emit_tool",
        description="x",
        category=ToolCategory.CHANGE_PLAN,
        artifact_spec=ArtifactSpec(kind="MONITOR", status_on_success="applied"),
    )

    async def fake_handler(args):
        return ToolResult(success=True, data={"title": "ok", "payload": {"kind": "MONITOR"}})

    executor._execute_flaky_emit_tool = fake_handler  # type: ignore

    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        # Simulate a transient persistence failure
        repo_instance.upsert.side_effect = RuntimeError("artifact API down")
        RepoCls.return_value = repo_instance

        result = await executor._execute_tool(tool, {"__tool_call_id": "tc_flaky"})

    # Tool result must still be the successful original result, not None or error
    assert result.success is True
    assert result.data["title"] == "ok"
    # Repo was called (verifying the emit path was attempted)
    repo_instance.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_emit_refines_pr_change_to_dbt_core_change_when_all_sql_models():
    from scanner.copilot.tool_executor import ToolExecutor

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_1"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_1"
    ctx._active_agent_session_id = None

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="create_change_plan",
        description="x",
        category=ToolCategory.CHANGE_PLAN,
        artifact_spec=ArtifactSpec(kind="PR_CHANGE", status_on_success="proposed"),
    )

    async def fake_handler(args):
        return ToolResult(
            success=True,
            data={
                "title": "dbt change",
                "summary": "edit 2 models",
                "payload": {
                    "kind": "PR_CHANGE",
                    "changePlanId": "cp_1",
                    "filesChanged": 2,
                    "diffSummary": "",
                    "validationResults": {},
                },
                "patches": [
                    {"patch_type": "sql_model", "file_path": "models/orders.sql"},
                    {"patch_type": "sql_model", "file_path": "models/customers.sql"},
                ],
            },
        )

    executor._execute_create_change_plan = fake_handler  # type: ignore

    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = {"id": "art_x"}
        RepoCls.return_value = repo_instance

        await executor._execute_tool(tool, {"__tool_call_id": "tc_1"})

    kwargs = repo_instance.upsert.await_args.kwargs
    assert kwargs["kind"].value == "DBT_CORE_CHANGE"


@pytest.mark.asyncio
async def test_auto_emit_refines_pr_change_to_dag_when_all_orchestration():
    from scanner.copilot.tool_executor import ToolExecutor

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_1"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_1"
    ctx._active_agent_session_id = None

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="create_change_plan",
        description="x",
        category=ToolCategory.CHANGE_PLAN,
        artifact_spec=ArtifactSpec(kind="PR_CHANGE", status_on_success="proposed"),
    )

    async def fake_handler(args):
        return ToolResult(
            success=True,
            data={
                "title": "dag edit",
                "payload": {"kind": "PR_CHANGE", "changePlanId": "cp_2", "filesChanged": 1, "diffSummary": "", "validationResults": {}},
                "patches": [{"patch_type": "orchestration", "file_path": "dags/my_dag.py"}],
            },
        )

    executor._execute_create_change_plan = fake_handler  # type: ignore

    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = {"id": "art_y"}
        RepoCls.return_value = repo_instance

        await executor._execute_tool(tool, {"__tool_call_id": "tc_2"})

    kwargs = repo_instance.upsert.await_args.kwargs
    assert kwargs["kind"].value == "DAG"


@pytest.mark.asyncio
async def test_auto_emit_reuses_begin_artefact_row_by_agent_session_id():
    """When _execute_begin_artefact has stashed an active agent session on the
    context, _emit_for_tool must key the artefact upsert by that session so the
    subsequent write-tool call UPDATES the draft row instead of creating a new
    duplicate, and must propagate the tool's risk_level.
    """
    from scanner.copilot.tool_executor import ToolExecutor
    from scanner.copilot.artifacts.models import ArtifactRisk

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_parent"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_1"
    # Simulate begin_artefact having stashed the child session on the context.
    ctx._active_agent_session_id = "sess_abc"
    ctx._active_agent_session_kind = "MONITOR"

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    tool = Tool(
        name="fake_write_tool",
        description="x",
        category=ToolCategory.CHANGE_PLAN,
        risk_level=RiskLevel.HIGH,
        artifact_spec=ArtifactSpec(kind="MONITOR", status_on_success="applied"),
    )

    async def fake_handler(args):
        return ToolResult(
            success=True,
            data={
                "title": "Test monitor",
                "payload": {"kind": "MONITOR", "monitorId": "m_1", "monitorKind": "FRESHNESS"},
            },
        )

    executor._execute_fake_write_tool = fake_handler  # type: ignore

    with patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = {"id": "art_reused"}
        RepoCls.return_value = repo_instance

        await executor._execute_tool(tool, {"__tool_call_id": "tc_write_1"})

    kwargs = repo_instance.upsert.await_args.kwargs
    assert kwargs["idempotency_key"] == "agent_session:sess_abc"
    assert kwargs["agent_session_id"] == "sess_abc"
    assert kwargs["risk_level"] == ArtifactRisk.HIGH
