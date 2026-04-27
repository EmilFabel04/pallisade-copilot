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
