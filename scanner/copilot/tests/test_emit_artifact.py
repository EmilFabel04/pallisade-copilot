"""Tests for emit_artifact helper."""
import pytest
from unittest.mock import AsyncMock, patch

from scanner.copilot.artifacts.emitter import emit_artifact
from scanner.copilot.artifacts.models import (
    ArtifactKind, ArtifactSpec, ArtifactStatus, MonitorPayload,
)


@pytest.mark.asyncio
async def test_emit_artifact_calls_repo_upsert_with_idempotency_key():
    spec = ArtifactSpec(
        kind=ArtifactKind.MONITOR.value,
        status_on_success=ArtifactStatus.applied.value,
    )
    payload = MonitorPayload(
        monitorId="mon_123",
        monitorKind="FRESHNESS",
        targetFqn="analytics.orders",
    )

    fake_repo = AsyncMock()
    fake_repo.upsert.return_value = {"id": "art_abc"}

    result = await emit_artifact(
        repo=fake_repo,
        spec=spec,
        tool_call_id="tc_42",
        agent_run_id="run_99",
        source_session_id="sess_parent",
        agent_session_id="sess_child",
        payload=payload,
        title="Freshness monitor on analytics.orders",
        summary="6h threshold",
        status=ArtifactStatus.applied,
        external_ref={"monitor_id": "mon_123"},
    )

    assert result == {"id": "art_abc"}
    fake_repo.upsert.assert_awaited_once()
    kwargs = fake_repo.upsert.await_args.kwargs
    # When agent_session_id is provided, the emitter keys by the session so that
    # begin_artefact's draft row and subsequent write-tool emits collapse to one row.
    assert kwargs["idempotency_key"] == "agent_session:sess_child"
    assert kwargs["kind"] == ArtifactKind.MONITOR
    assert kwargs["status"] == ArtifactStatus.applied
    assert kwargs["payload"]["monitorId"] == "mon_123"
    assert kwargs["external_ref"] == {"monitor_id": "mon_123"}


@pytest.mark.asyncio
async def test_emit_artifact_serialises_pydantic_payload():
    spec = ArtifactSpec(kind=ArtifactKind.MONITOR.value)
    fake_repo = AsyncMock()
    fake_repo.upsert.return_value = {"id": "art_xyz"}

    payload = MonitorPayload(monitorId="m1", monitorKind="VOLUME")
    await emit_artifact(
        repo=fake_repo,
        spec=spec,
        tool_call_id="tc_1",
        agent_run_id="r_1",
        payload=payload,
        title="t",
        status=ArtifactStatus.proposed,
    )

    kwargs = fake_repo.upsert.await_args.kwargs
    # Payload must be serialisable JSON (dict, not BaseModel instance)
    assert isinstance(kwargs["payload"], dict)
    assert kwargs["payload"]["kind"] == "MONITOR"
    # No agent_session_id was provided, so the emitter falls back to the tool_call_id+kind key.
    assert kwargs["idempotency_key"] == "tc_1:MONITOR"
