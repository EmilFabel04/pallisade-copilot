"""Tests for write tool executors: create_watch and run_watch."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from scanner.copilot.artifacts import ToolArtifactResult


@pytest.mark.asyncio
async def test_execute_create_watch_returns_artifact():
    """create_watch should return a ToolArtifactResult, not execute immediately."""
    from scanner.copilot.tool_executor import ToolExecutor

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"

    executor = ToolExecutor(mock_context)
    result = await executor.execute("create_watch", {
        "name": "Orders Health",
        "watch_type": "pipeline_health",
        "anchor_fqn": "analytics.public.orders",
        "monitors": [
            {"monitor_type": "FRESHNESS", "target_fqn": "analytics.public.orders", "config": {"timestamp_column": "updated_at"}},
        ],
        "schedule": "0 */6 * * *",
        "timezone": "UTC",
    })

    assert isinstance(result, ToolArtifactResult)
    assert result.artifact_type == "watch_preview"
    assert result.action == "create"
    assert result.confirmation_tier == "inline"  # 1 monitor = inline
    assert result.data["name"] == "Orders Health"
    assert result.data["watchType"] == "pipeline_health"
    assert len(result.data["monitors"]) == 1


@pytest.mark.asyncio
async def test_create_watch_modal_tier_for_many_monitors():
    """create_watch with 5+ monitors should use modal confirmation."""
    from scanner.copilot.tool_executor import ToolExecutor

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"

    executor = ToolExecutor(mock_context)
    monitors = [
        {"monitor_type": t, "target_fqn": "analytics.public.orders"}
        for t in ["FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "ANOMALY", "NULL_CHECK"]
    ]
    result = await executor.execute("create_watch", {
        "name": "Orders Full Coverage",
        "watch_type": "pipeline_health",
        "anchor_fqn": "analytics.public.orders",
        "monitors": monitors,
        "schedule": "0 */6 * * *",
    })

    assert isinstance(result, ToolArtifactResult)
    assert result.confirmation_tier == "modal"  # 5 monitors = modal


@pytest.mark.asyncio
async def test_create_watch_executes_when_confirmed():
    """When confirmed_data is passed, create_watch should call the 3-step pipeline."""
    from scanner.copilot.tool_executor import ToolExecutor, ToolResult

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"
    mock_context.pipeline_stack_id = ""
    mock_context.graph = None

    executor = ToolExecutor(mock_context)

    confirmed_data = {
        "name": "Orders Health",
        "watchType": "pipeline_health",
        "anchorFqn": "analytics.public.orders",
        "monitors": [{"monitor_type": "FRESHNESS", "target_fqn": "analytics.public.orders"}],
        "schedule": "0 */6 * * *",
        "timezone": "UTC",
    }

    # Mock the 3-step pipeline: preview, policy resolve, plans create
    preview_response = {
        "groups": [{
            "anchor_name": "orders",
            "anchor_fqn": "analytics.public.orders",
            "anchor_id": "",
            "anchor_node_type": "table",
            "anchor_platform": "bigquery",
            "watch_type": "pipeline_health",
            "recommendations": [{
                "monitor_key": "FRESHNESS",
                "target_fqn": "analytics.public.orders",
                "config_hints": {"max_hours": 24},
            }],
        }],
    }
    policy_response = {"policies": {}}
    plans_response = {"id": "plan_123", "name": "Orders Health", "totalMonitors": 1}

    async def mock_call_fastapi(path, body):
        if "preview" in path:
            return preview_response
        if "policies" in path:
            return policy_response
        return {}

    async def mock_call_nextjs(path, body):
        return plans_response

    with patch.object(executor, '_call_fastapi', side_effect=mock_call_fastapi), \
         patch.object(executor, '_call_nextjs', side_effect=mock_call_nextjs):
        result = await executor.execute_confirmed("create_watch", confirmed_data)

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.data["planId"] == "plan_123"
    assert result.data["monitorCount"] == 1
