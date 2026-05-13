"""Tests for _execute_begin_artefact — child session fork + artefact draft row."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.copilot.artifacts.models import ArtifactKind, ArtifactStatus


@pytest.mark.asyncio
async def test_begin_artefact_creates_child_session_and_draft_row():
    from scanner.copilot.tool_executor import ToolExecutor

    ctx = MagicMock()
    ctx.org_id = "org_1"
    ctx.user_id = "u_1"
    ctx.session_id = "sess_parent"
    ctx.base_url = "http://localhost:3000"
    ctx.agent_run_id = "run_42"

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.context = ctx

    # Mock the session-fork endpoint and the artefact repo
    with patch("scanner.copilot.tool_executor.fork_copilot_session", new=AsyncMock(return_value="sess_child")) as fork_mock, \
         patch("scanner.copilot.tool_executor.ArtifactRepo") as RepoCls:
        repo_instance = AsyncMock()
        repo_instance.upsert.return_value = {"id": "art_1", "agentSessionId": "sess_child"}
        RepoCls.return_value = repo_instance

        result = await executor._execute_begin_artefact({
            "kind": "MONITOR",
            "intent": "Add freshness monitor on analytics.orders",
            "subtype": None,
        })

    assert result.success is True
    assert result.data["artefact_id"] == "art_1"
    assert result.data["agent_session_id"] == "sess_child"
    fork_mock.assert_awaited_once_with(
        base_url="http://localhost:3000",
        org_id="org_1",
        user_id="u_1",
        parent_session_id="sess_parent",
        title="Add freshness monitor on analytics.orders",
    )
    repo_instance.upsert.assert_awaited_once()
    kwargs = repo_instance.upsert.await_args.kwargs
    assert kwargs["kind"] == ArtifactKind.MONITOR
    assert kwargs["status"] == ArtifactStatus.draft
    assert kwargs["agent_session_id"] == "sess_child"
    assert kwargs["source_session_id"] == "sess_parent"
    # Identity key must be session-based so the subsequent write-tool auto-emit
    # UPDATEs this draft row instead of creating a duplicate.
    assert kwargs["idempotency_key"] == "agent_session:sess_child"
    # Context must be stashed for _emit_for_tool to pick up.
    assert ctx._active_agent_session_id == "sess_child"
    assert ctx._active_agent_session_kind == "MONITOR"
