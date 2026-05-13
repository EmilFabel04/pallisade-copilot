"""Tests for create/update/delete_monitor tool executors."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.copilot.tool_executor import ToolExecutor
from scanner.copilot.tools.base import ToolResult


def _make_executor():
    ctx = MagicMock()
    ctx.base_url = "http://localhost:3000"
    ctx.org_id = "org_1"
    ctx.user_id = "user_1"
    ctx.session_id = "sess_1"
    ctx.agent_run_id = "run_1"
    ctx.pipeline_stack_id = "stack_1"
    ctx.graph = None
    return ToolExecutor(ctx)


@pytest.mark.asyncio
async def test_create_monitor_returns_artefact_payload():
    ex = _make_executor()
    fake_plan = {
        "id": "plan_42",
        "groups": [{"monitors": [{"id": "mon_99"}]}],
    }
    with patch.object(ex, "_call_nextjs", new=AsyncMock(return_value=fake_plan)):
        result = await ex._execute_create_monitor({
            "target_fqn": "warehouse.analytics.orders",
            "monitor_kind": "FRESHNESS",
            "config": {"maxHours": 6},
        })
    assert isinstance(result, ToolResult)
    assert result.success
    payload = result.data["payload"]
    assert payload["kind"] == "MONITOR"
    assert payload["monitorId"] == "mon_99"
    assert payload["monitorKind"] == "FRESHNESS"
    assert payload["targetFqn"] == "warehouse.analytics.orders"
    assert payload["configDiff"]["after"] == {"maxHours": 6}
    assert result.data["external_ref"]["monitor_id"] == "mon_99"
    assert result.data["external_ref"]["plan_id"] == "plan_42"


@pytest.mark.asyncio
async def test_create_monitor_rejects_missing_args():
    ex = _make_executor()
    r1 = await ex._execute_create_monitor({"monitor_kind": "FRESHNESS"})
    assert not r1.success and "required" in (r1.error or "")
    r2 = await ex._execute_create_monitor({"target_fqn": "x.y.z"})
    assert not r2.success and "required" in (r2.error or "")


@pytest.mark.asyncio
async def test_create_monitor_handles_empty_plan_response():
    ex = _make_executor()
    with patch.object(ex, "_call_nextjs", new=AsyncMock(return_value={"id": "plan_1", "groups": []})):
        result = await ex._execute_create_monitor({
            "target_fqn": "a.b.c",
            "monitor_kind": "VOLUME",
        })
    assert not result.success
    assert "no monitor row" in (result.error or "")


@pytest.mark.asyncio
async def test_update_monitor_returns_diff():
    ex = _make_executor()
    fake_response = {
        "monitorId": "mon_42",
        "monitorKind": "FRESHNESS",
        "targetFqn": "wh.s.t",
        "configDiff": {"before": {"maxHours": 4}, "after": {"maxHours": 6}},
    }
    with patch.object(ex, "_call_nextjs", new=AsyncMock(return_value=fake_response)) as mocked:
        result = await ex._execute_update_monitor({
            "monitor_id": "mon_42",
            "config": {"maxHours": 6},
        })
    assert result.success
    mocked.assert_awaited_once()
    called_path = mocked.await_args.args[0]
    assert called_path == "/api/monitors/internal/mon_42/update"
    assert result.data["payload"]["configDiff"]["before"] == {"maxHours": 4}
    assert result.data["payload"]["configDiff"]["after"] == {"maxHours": 6}


@pytest.mark.asyncio
async def test_update_monitor_rejects_empty_config():
    ex = _make_executor()
    r = await ex._execute_update_monitor({"monitor_id": "mon_1", "config": {}})
    assert not r.success and "non-empty" in (r.error or "")


@pytest.mark.asyncio
async def test_delete_monitor_returns_audit_payload():
    ex = _make_executor()
    fake_response = {
        "monitorId": "mon_77",
        "monitorKind": "VOLUME",
        "targetFqn": "wh.s.orders",
        "deleted": True,
    }
    with patch.object(ex, "_delete_nextjs", new=AsyncMock(return_value=fake_response)) as mocked:
        result = await ex._execute_delete_monitor({"monitor_id": "mon_77"})
    assert result.success
    mocked.assert_awaited_once_with("/api/monitors/internal/mon_77")
    assert result.data["payload"]["kind"] == "MONITOR"
    assert result.data["payload"]["configDiff"]["operation"] == "delete"
    assert result.data["external_ref"]["deleted"] is True


@pytest.mark.asyncio
async def test_delete_monitor_rejects_missing_id():
    ex = _make_executor()
    r = await ex._execute_delete_monitor({})
    assert not r.success and "required" in (r.error or "")
