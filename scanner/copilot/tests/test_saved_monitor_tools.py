"""Tests for the saved-monitor visibility tools (list_configured_monitors,
get_monitor_run_history) — both POST to Next.js via _call_nextjs."""
import pytest
from unittest.mock import AsyncMock

from copilot.context_builder import CopilotContext
from copilot.tool_executor import ToolExecutor


def _ctx() -> CopilotContext:
    return CopilotContext(
        org_id="org_1",
        base_url="http://localhost:3000",
        auth_token="copilot-token",
    )


@pytest.mark.asyncio
async def test_list_configured_monitors_posts_filters_to_nextjs():
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock(return_value={
        "monitors": [
            {
                "id": "mon_1",
                "name": "orders source validation",
                "monitorType": "DBT_CORE_SOURCE_VALIDATION",
                "targetFqn": "analytics.orders",
                "enabled": True,
                "lastStatus": "FAIL",
                "lastRunAt": "2026-04-27T06:00:00Z",
            }
        ],
        "total": 1,
    })

    result = await executor.execute("list_configured_monitors", {
        "monitor_type": "DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY",
        "status": "FAIL,ERROR",
        "limit": 25,
    })

    assert result.success is True
    assert len(result.data["monitors"]) == 1
    assert result.data["monitors"][0]["id"] == "mon_1"

    executor._call_nextjs.assert_awaited_once()
    path, body = executor._call_nextjs.await_args.args
    assert path == "/api/copilot/internal/list-configured-monitors"
    assert body == {
        "monitor_type": "DBT_CORE_SOURCE_VALIDATION,DBT_CORE_REF_INTEGRITY",
        "status": "FAIL,ERROR",
        "limit": 25,
    }


@pytest.mark.asyncio
async def test_list_configured_monitors_surfaces_endpoint_errors():
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock(side_effect=Exception("Next.js /... failed (500): db down"))

    result = await executor.execute("list_configured_monitors", {})

    assert result.success is False
    assert "db down" in (result.error or "")


@pytest.mark.asyncio
async def test_get_monitor_run_history_posts_to_nextjs():
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock(return_value={
        "monitor": {
            "id": "mon_1",
            "name": "orders source validation",
            "monitorType": "DBT_CORE_SOURCE_VALIDATION",
            "targetFqn": "analytics.orders",
        },
        "runs": [
            {
                "id": "run_2",
                "status": "FAIL",
                "message": "source freshness exceeded threshold",
                "startedAt": "2026-04-27T06:00:00Z",
                "completedAt": "2026-04-27T06:00:02Z",
                "durationMs": 2000,
            }
        ],
        "total": 1,
    })

    result = await executor.execute("get_monitor_run_history", {
        "monitor_id": "mon_1",
        "limit": 5,
    })

    assert result.success is True
    assert result.data["runs"][0]["status"] == "FAIL"

    path, body = executor._call_nextjs.await_args.args
    assert path == "/api/copilot/internal/get-monitor-run-history"
    assert body == {"monitor_id": "mon_1", "limit": 5}


@pytest.mark.asyncio
async def test_get_monitor_run_history_requires_monitor_id():
    """The tool itself should reject a call without monitor_id rather than
    making a doomed network call."""
    executor = ToolExecutor(_ctx())
    executor._call_nextjs = AsyncMock()

    result = await executor.execute("get_monitor_run_history", {})

    assert result.success is False
    assert "monitor_id" in (result.error or "").lower()
    executor._call_nextjs.assert_not_awaited()


def test_saved_monitor_tools_are_always_available():
    from copilot.context_builder import CopilotContextBuilder

    builder = CopilotContextBuilder.__new__(CopilotContextBuilder)
    # Empty integration set — these tools must still be offered.
    tools = builder._get_available_tools(set())
    assert "list_configured_monitors" in tools
    assert "get_monitor_run_history" in tools
