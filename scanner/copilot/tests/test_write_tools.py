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
